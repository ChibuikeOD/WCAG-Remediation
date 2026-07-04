"""Atomic lifecycle operations for trial page grants and reservations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import RemediationJob, TrialAccount, TrialLedgerEntry, User

from .eligibility import classify_verified_email


@dataclass(frozen=True)
class TrialBalance:
    granted: int
    consumed: int
    reserved: int
    remaining: int


class InsufficientPages(Exception):
    """A safe, user-displayable error for exhausted trial quota."""

    def __init__(self, requested: int, remaining: int):
        super().__init__("Insufficient trial pages")
        self.requested = requested
        self.remaining = remaining


class TrialStateError(Exception):
    """Raised when persisted trial state cannot support an operation."""


class TrialService:
    """Coordinate trial ledger writes and job transitions in one transaction."""

    def __init__(self, session: Session):
        self.session = session

    def ensure_account(self, user: User) -> TrialAccount:
        existing = self.session.get(TrialAccount, user.id)
        if existing is not None:
            self._validate_account_grant(existing)
            return existing

        decision = classify_verified_email(user.email)
        account = TrialAccount(
            user_id=user.id,
            normalized_email=decision.normalized_email,
            normalized_domain=decision.normalized_domain,
            granted_pages=decision.granted_pages,
            eligibility_rule_version=decision.rule_version,
        )
        grant = TrialLedgerEntry(
            id=str(uuid4()),
            user_id=user.id,
            entry_type="grant",
            granted_delta=decision.granted_pages,
            reserved_delta=0,
            consumed_delta=0,
            idempotency_key=f"grant:{decision.rule_version}",
        )
        self.session.add_all((account, grant))
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.get(TrialAccount, user.id)
            if existing is None:
                raise
            self._validate_account_grant(existing)
            return existing
        return account

    def get_balance(self, user_id: str) -> TrialBalance:
        if self.session.get(TrialAccount, user_id) is None:
            raise TrialStateError("trial account does not exist")
        return self._get_balance(user_id)

    def reserve(
        self, user_id: str, job_id: str, pages: int, key: str
    ) -> TrialBalance:
        if not isinstance(pages, int) or isinstance(pages, bool) or pages <= 0:
            raise ValueError("pages must be a positive integer")
        try:
            self._lock_account(user_id)
            job = self._lock_job(job_id)
            if job is None or job.user_id != user_id:
                raise TrialStateError("remediation job does not belong to user")
            if job.page_count != pages:
                raise TrialStateError("pages must match authoritative job page count")

            existing = self.session.scalar(
                select(TrialLedgerEntry).where(
                    TrialLedgerEntry.user_id == user_id,
                    TrialLedgerEntry.idempotency_key == key,
                )
            )
            if existing is not None:
                if not self._matches_reserve(existing, job_id, pages):
                    raise TrialStateError("idempotency key conflicts with reservation")
                if job.status != "reserved":
                    raise TrialStateError(
                        "idempotent reservation requires a reserved job"
                    )
                result = self._get_balance(user_id)
                self.session.commit()
                return result

            if job.status != "pending":
                raise TrialStateError("remediation job must be pending")

            balance = self._get_balance(user_id)
            if pages > balance.remaining:
                raise InsufficientPages(pages, balance.remaining)

            self.session.add(
                TrialLedgerEntry(
                    id=str(uuid4()),
                    user_id=user_id,
                    job_id=job_id,
                    entry_type="reserve",
                    granted_delta=0,
                    reserved_delta=pages,
                    consumed_delta=0,
                    idempotency_key=key,
                )
            )
            job.status = "reserved"
            self.session.flush()
            result = self._get_balance(user_id)
            self.session.commit()
            return result
        except Exception:
            self.session.rollback()
            raise

    def consume(self, job_id: str) -> TrialBalance:
        try:
            unlocked_job = self.session.get(RemediationJob, job_id)
            if unlocked_job is None:
                raise TrialStateError("remediation job does not exist")
            self._lock_account(unlocked_job.user_id)
            job = self._lock_job(job_id)
            if job is None or job.user_id != unlocked_job.user_id:
                raise TrialStateError("remediation job ownership changed")
            key = f"consume:{job_id}"
            existing = self._entry_for_key(job.user_id, key)
            if job.status == "succeeded":
                if not self._matches_consume(existing, job_id, job.page_count):
                    raise TrialStateError("succeeded job has invalid consume entry")
                result = self._get_balance(job.user_id)
                self.session.commit()
                return result
            if job.status != "reserved":
                raise TrialStateError("only a reserved job can be consumed")
            if existing is not None:
                raise TrialStateError("consume idempotency state conflicts with job")
            self._require_active_reservation(job)

            self.session.add(
                TrialLedgerEntry(
                    id=str(uuid4()),
                    user_id=job.user_id,
                    job_id=job.id,
                    entry_type="consume",
                    granted_delta=0,
                    reserved_delta=-job.page_count,
                    consumed_delta=job.page_count,
                    idempotency_key=key,
                )
            )
            job.status = "succeeded"
            job.completed_at = datetime.now(timezone.utc)
            self.session.flush()
            result = self._get_balance(job.user_id)
            self.session.commit()
            return result
        except Exception:
            self.session.rollback()
            raise

    def release(self, job_id: str, reason: str) -> TrialBalance:
        try:
            unlocked_job = self.session.get(RemediationJob, job_id)
            if unlocked_job is None:
                raise TrialStateError("remediation job does not exist")
            self._lock_account(unlocked_job.user_id)
            job = self._lock_job(job_id)
            if job is None or job.user_id != unlocked_job.user_id:
                raise TrialStateError("remediation job ownership changed")
            key = f"release:{job_id}"
            existing = self._entry_for_key(job.user_id, key)
            if job.status == "released":
                if job.failure_reason != reason:
                    raise TrialStateError("release reason conflicts with prior release")
                if not self._matches_release(existing, job_id, job.page_count):
                    raise TrialStateError("released job has invalid release entry")
                result = self._get_balance(job.user_id)
                self.session.commit()
                return result
            if job.status not in {"reserved", "processing"}:
                raise TrialStateError("job cannot be released from its current state")
            if existing is not None:
                raise TrialStateError("release idempotency state conflicts with job")
            self._require_active_reservation(job)

            self.session.add(
                TrialLedgerEntry(
                    id=str(uuid4()),
                    user_id=job.user_id,
                    job_id=job.id,
                    entry_type="release",
                    granted_delta=0,
                    reserved_delta=-job.page_count,
                    consumed_delta=0,
                    idempotency_key=key,
                )
            )
            job.status = "released"
            job.failure_reason = reason
            job.completed_at = datetime.now(timezone.utc)
            self.session.flush()
            result = self._get_balance(job.user_id)
            self.session.commit()
            return result
        except Exception:
            self.session.rollback()
            raise

    def _lock_account(self, user_id: str) -> TrialAccount:
        account = self.session.scalar(
            select(TrialAccount)
            .where(TrialAccount.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if account is None:
            raise TrialStateError("trial account does not exist")
        return account

    def _lock_job(self, job_id: str) -> RemediationJob | None:
        return self.session.scalar(
            select(RemediationJob)
            .where(RemediationJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _get_balance(self, user_id: str) -> TrialBalance:
        totals = self.session.execute(
            select(
                func.coalesce(func.sum(TrialLedgerEntry.granted_delta), 0),
                func.coalesce(func.sum(TrialLedgerEntry.consumed_delta), 0),
                func.coalesce(func.sum(TrialLedgerEntry.reserved_delta), 0),
            ).where(TrialLedgerEntry.user_id == user_id)
        ).one()
        granted, consumed, reserved = (int(value) for value in totals)
        remaining = granted - reserved - consumed
        account = self.session.get(TrialAccount, user_id)
        if (
            account is None
            or granted != account.granted_pages
            or min(granted, consumed, reserved, remaining) < 0
        ):
            raise TrialStateError("invalid trial balance")
        return TrialBalance(granted, consumed, reserved, remaining)

    def _validate_account_grant(self, account: TrialAccount) -> None:
        grants = self.session.scalars(
            select(TrialLedgerEntry).where(
                TrialLedgerEntry.user_id == account.user_id,
                TrialLedgerEntry.entry_type == "grant",
            )
        ).all()
        expected_key = f"grant:{account.eligibility_rule_version}"
        if (
            len(grants) != 1
            or grants[0].idempotency_key != expected_key
            or not self._matches_grant(grants[0], account.granted_pages)
        ):
            raise TrialStateError("trial grant state conflicts with account provenance")

    def _entry_for_key(self, user_id: str, key: str) -> TrialLedgerEntry | None:
        return self.session.scalar(
            select(TrialLedgerEntry).where(
                TrialLedgerEntry.user_id == user_id,
                TrialLedgerEntry.idempotency_key == key,
            )
        )

    def _require_active_reservation(self, job: RemediationJob) -> None:
        rows = self.session.scalars(
            select(TrialLedgerEntry).where(
                TrialLedgerEntry.user_id == job.user_id,
                TrialLedgerEntry.job_id == job.id,
            )
        ).all()
        reserves = [row for row in rows if row.entry_type == "reserve"]
        active = sum(row.reserved_delta for row in rows)
        if (
            len(reserves) != 1
            or reserves[0].reserved_delta != job.page_count
            or active != job.page_count
        ):
            raise TrialStateError("job does not have an exact active reservation")

    @staticmethod
    def _matches_grant(entry: TrialLedgerEntry | None, pages: int) -> bool:
        return bool(
            entry
            and entry.entry_type == "grant"
            and entry.job_id is None
            and entry.granted_delta == pages
            and entry.reserved_delta == 0
            and entry.consumed_delta == 0
        )

    @staticmethod
    def _matches_reserve(entry: TrialLedgerEntry, job_id: str, pages: int) -> bool:
        return (
            entry.entry_type == "reserve"
            and entry.job_id == job_id
            and entry.granted_delta == 0
            and entry.reserved_delta == pages
            and entry.consumed_delta == 0
        )

    @staticmethod
    def _matches_consume(
        entry: TrialLedgerEntry | None, job_id: str, pages: int
    ) -> bool:
        return bool(
            entry
            and entry.entry_type == "consume"
            and entry.job_id == job_id
            and entry.granted_delta == 0
            and entry.reserved_delta == -pages
            and entry.consumed_delta == pages
        )

    @staticmethod
    def _matches_release(
        entry: TrialLedgerEntry | None, job_id: str, pages: int
    ) -> bool:
        return bool(
            entry
            and entry.entry_type == "release"
            and entry.job_id == job_id
            and entry.granted_delta == 0
            and entry.reserved_delta == -pages
            and entry.consumed_delta == 0
        )
