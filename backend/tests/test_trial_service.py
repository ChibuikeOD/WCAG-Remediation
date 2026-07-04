"""Behavior tests for atomic trial account and page-ledger operations."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import datetime
import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from backend import database
from backend.trial.service import (
    InsufficientPages,
    TrialBalance,
    TrialService,
    TrialStateError,
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'trial-service.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    database.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        database.Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def add_user(db, user_id="user-1", email="person@gmail.com"):
    user = database.User(id=user_id, email=email, name=user_id)
    db.add(user)
    db.commit()
    return user


def add_job(db, user, job_id="job-1", pages=2, status="pending"):
    job = database.RemediationJob(
        id=job_id,
        user_id=user.id,
        status=status,
        page_count=pages,
        idempotency_key=f"job:{job_id}",
    )
    db.add(job)
    db.commit()
    return job


def entries(db, user_id):
    return db.scalars(
        select(database.TrialLedgerEntry)
        .where(database.TrialLedgerEntry.user_id == user_id)
        .order_by(database.TrialLedgerEntry.created_at)
    ).all()


@pytest.mark.parametrize(
    ("email", "pages"),
    [("person@gmail.com", 200), ("person@university.edu", 400)],
)
def test_ensure_account_creates_one_classified_grant(db, email, pages):
    user = add_user(db, email=email)

    account = TrialService(db).ensure_account(user)

    assert account.user_id == user.id
    assert account.granted_pages == pages
    assert account.normalized_email == email
    assert account.eligibility_rule_version == "2026-07-04"
    [grant] = entries(db, user.id)
    assert (grant.entry_type, grant.granted_delta, grant.idempotency_key) == (
        "grant",
        pages,
        "grant:2026-07-04",
    )


def test_ensure_account_is_repeatable_without_duplicate_grant(db):
    user = add_user(db)
    service = TrialService(db)

    first = service.ensure_account(user)
    second = service.ensure_account(user)

    assert first.user_id == second.user_id
    assert len(entries(db, user.id)) == 1


def test_ensure_account_rejects_existing_account_without_matching_grant(db):
    user = add_user(db)
    db.add(
        database.TrialAccount(
            user_id=user.id,
            normalized_email="person@gmail.com",
            normalized_domain="gmail.com",
            granted_pages=200,
            eligibility_rule_version="2026-07-04",
        )
    )
    db.commit()

    with pytest.raises(TrialStateError, match="grant"):
        TrialService(db).ensure_account(user)


def test_concurrent_first_account_creation_has_one_grant(session_factory):
    seed = session_factory()
    user = add_user(seed)
    user_id = user.id
    seed.close()
    barrier = threading.Barrier(2)

    def ensure():
        session = session_factory()
        try:
            local_user = session.get(database.User, user_id)
            barrier.wait()
            return TrialService(session).ensure_account(local_user).user_id
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _index: ensure(), range(2))) == [
            user_id,
            user_id,
        ]

    check = session_factory()
    try:
        assert check.query(database.TrialAccount).count() == 1
        assert check.query(database.TrialLedgerEntry).count() == 1
    finally:
        check.close()


def test_trial_balance_is_frozen_and_derived_from_ledger(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=3)
    service.reserve(user.id, job.id, 3, "request-1")

    balance = service.get_balance(user.id)

    assert balance == TrialBalance(granted=200, consumed=0, reserved=3, remaining=197)
    with pytest.raises(FrozenInstanceError):
        balance.remaining = 999


def test_get_balance_rejects_impossible_negative_aggregates(db):
    user = add_user(db)
    TrialService(db).ensure_account(user)
    job = add_job(db, user, pages=201)
    db.add(
        database.TrialLedgerEntry(
            id="corrupt-reserve",
            user_id=user.id,
            job_id=job.id,
            entry_type="reserve",
            reserved_delta=201,
            idempotency_key="corrupt-reserve",
        )
    )
    db.commit()

    with pytest.raises(TrialStateError, match="invalid trial balance"):
        TrialService(db).get_balance(user.id)


def test_get_balance_rejects_negative_reserved_aggregate(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=1)
    service.reserve(user.id, job.id, 1, "reserve")
    db.add(
        database.TrialLedgerEntry(
            id="extra-release",
            user_id=user.id,
            job_id=job.id,
            entry_type="release",
            reserved_delta=-2,
            idempotency_key="extra-release",
        )
    )
    db.commit()

    with pytest.raises(TrialStateError, match="invalid trial balance"):
        service.get_balance(user.id)


def test_get_balance_rejects_grant_that_conflicts_with_account_provenance(db):
    user = add_user(db)
    db.add(
        database.TrialAccount(
            user_id=user.id,
            normalized_email="person@gmail.com",
            normalized_domain="gmail.com",
            granted_pages=200,
            eligibility_rule_version="2026-07-04",
        )
    )
    db.add(
        database.TrialLedgerEntry(
            id="wrong-grant",
            user_id=user.id,
            entry_type="grant",
            granted_delta=400,
            idempotency_key="grant:wrong",
        )
    )
    db.commit()

    with pytest.raises(TrialStateError, match="invalid trial balance"):
        TrialService(db).get_balance(user.id)


def test_balance_and_reserve_reject_two_grants_that_sum_to_account_total(db):
    user = add_user(db)
    db.add(
        database.TrialAccount(
            user_id=user.id,
            normalized_email="person@gmail.com",
            normalized_domain="gmail.com",
            granted_pages=200,
            eligibility_rule_version="2026-07-04",
        )
    )
    db.add_all(
        [
            database.TrialLedgerEntry(
                id=f"split-grant-{index}",
                user_id=user.id,
                entry_type="grant",
                granted_delta=100,
                idempotency_key=f"split-grant:{index}",
            )
            for index in range(2)
        ]
    )
    job = database.RemediationJob(
        id="job-1",
        user_id=user.id,
        status="pending",
        page_count=3,
        idempotency_key="job:job-1",
    )
    db.add(job)
    db.commit()
    service = TrialService(db)

    with pytest.raises(TrialStateError, match="grant"):
        service.get_balance(user.id)
    db.rollback()
    with pytest.raises(TrialStateError, match="grant"):
        service.reserve(user.id, job.id, 3, "reserve")

    assert len(entries(db, user.id)) == 2


def test_reserve_moves_pending_job_and_appends_delta(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=8)

    balance = service.reserve(user.id, job.id, 8, "reserve-request")

    assert balance == TrialBalance(200, 0, 8, 192)
    assert db.get(database.RemediationJob, job.id).status == "reserved"
    reserve = entries(db, user.id)[1]
    assert (reserve.job_id, reserve.entry_type, reserve.reserved_delta) == (
        job.id,
        "reserve",
        8,
    )
    assert reserve.idempotency_key == "reserve-request"


@pytest.mark.parametrize("pages", [0, -1])
def test_reserve_rejects_nonpositive_pages_without_mutation(db, pages):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user)

    with pytest.raises(ValueError, match="positive"):
        service.reserve(user.id, job.id, pages, "bad-pages")

    assert db.get(database.RemediationJob, job.id).status == "pending"
    assert len(entries(db, user.id)) == 1


def test_reserve_requires_account_owner_pending_job_and_authoritative_pages(db):
    owner = add_user(db)
    stranger = add_user(db, "user-2", "other@gmail.com")
    service = TrialService(db)
    service.ensure_account(owner)
    service.ensure_account(stranger)
    job = add_job(db, owner, pages=4)

    with pytest.raises(TrialStateError):
        service.reserve(stranger.id, job.id, 4, "wrong-owner")
    with pytest.raises(TrialStateError, match="page count"):
        service.reserve(owner.id, job.id, 3, "wrong-pages")
    job.status = "processing"
    db.commit()
    with pytest.raises(TrialStateError, match="pending"):
        service.reserve(owner.id, job.id, 4, "wrong-state")


def test_reserve_requires_an_existing_account_and_job(db):
    user = add_user(db)
    service = TrialService(db)

    with pytest.raises(TrialStateError, match="account"):
        service.reserve(user.id, "missing", 1, "missing-account")

    service.ensure_account(user)
    with pytest.raises(TrialStateError, match="job"):
        service.reserve(user.id, "missing", 1, "missing-job")


def test_reserve_idempotency_requires_same_job_and_payload(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    first = add_job(db, user, "job-1", 3)
    second = add_job(db, user, "job-2", 3)

    expected = service.reserve(user.id, first.id, 3, "same-key")
    assert service.reserve(user.id, first.id, 3, "same-key") == expected
    with pytest.raises(TrialStateError, match="idempotency"):
        service.reserve(user.id, second.id, 3, "same-key")


def test_reserve_retry_rejects_authoritative_page_count_drift(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=3)
    service.reserve(user.id, job.id, 3, "same-key")
    job.page_count = 4
    db.commit()

    with pytest.raises(TrialStateError, match="page count"):
        service.reserve(user.id, job.id, 3, "same-key")

    assert len(entries(db, user.id)) == 2


def test_reserve_retry_rejects_illegal_changed_job_state(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=3)
    service.reserve(user.id, job.id, 3, "same-key")
    job.status = "processing"
    db.commit()

    with pytest.raises(TrialStateError, match="reserved"):
        service.reserve(user.id, job.id, 3, "same-key")

    assert len(entries(db, user.id)) == 2


def test_reserve_retry_rejects_missing_authoritative_job(db):
    user = add_user(db)
    user_id = user.id
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=3)
    job_id = job.id
    service.reserve(user_id, job_id, 3, "same-key")

    # Simulate external database corruption; the declared FK normally prevents
    # a job from disappearing while its immutable ledger history remains.
    connection = db.get_bind().raw_connection()
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DELETE FROM remediation_jobs WHERE id = ?", (job_id,))
        connection.commit()
        connection.execute("PRAGMA foreign_keys=ON")
    finally:
        connection.close()
    db.expire_all()

    with pytest.raises(TrialStateError, match="job"):
        service.reserve(user_id, job_id, 3, "same-key")

    assert len(entries(db, user_id)) == 2


def test_reserve_retry_rejects_release_hidden_by_reserved_status(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=3)
    service.reserve(user.id, job.id, 3, "reserve")
    db.add(
        database.TrialLedgerEntry(
            id="hidden-release",
            user_id=user.id,
            job_id=job.id,
            entry_type="release",
            reserved_delta=-3,
            idempotency_key="hidden-release",
        )
    )
    db.commit()

    with pytest.raises(TrialStateError, match="lifecycle"):
        service.reserve(user.id, job.id, 3, "reserve")

    assert len(entries(db, user.id)) == 3


def test_idempotent_retry_finishes_transaction_and_releases_locks(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=3)
    service.reserve(user.id, job.id, 3, "same-key")

    service.reserve(user.id, job.id, 3, "same-key")

    assert not db.in_transaction()


def test_insufficient_pages_is_safe_and_does_not_mutate(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=201)

    with pytest.raises(InsufficientPages) as caught:
        service.reserve(user.id, job.id, 201, "too-large")

    assert caught.value.requested == 201
    assert caught.value.remaining == 200
    assert str(caught.value) == "Insufficient trial pages"
    assert db.get(database.RemediationJob, job.id).status == "pending"
    assert len(entries(db, user.id)) == 1


def test_two_reservations_cannot_overspend(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    first = add_job(db, user, "job-1", 150)
    second = add_job(db, user, "job-2", 51)

    service.reserve(user.id, first.id, 150, "first")
    with pytest.raises(InsufficientPages):
        service.reserve(user.id, second.id, 51, "second")

    assert db.get(database.RemediationJob, second.id).status == "pending"


def test_consume_succeeds_and_is_idempotent(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=7)
    service.reserve(user.id, job.id, 7, "reserve")

    expected = service.consume(job.id)

    assert expected == TrialBalance(200, 7, 0, 193)
    stored = db.get(database.RemediationJob, job.id)
    assert stored.status == "succeeded"
    assert isinstance(stored.completed_at, datetime)
    assert service.consume(job.id) == expected
    assert [entry.entry_type for entry in entries(db, user.id)] == [
        "grant",
        "reserve",
        "consume",
    ]


def test_consume_retry_rejects_extra_reserve_release_pair(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=3)
    service.reserve(user.id, job.id, 3, "reserve")
    service.consume(job.id)
    db.add_all(
        [
            database.TrialLedgerEntry(
                id="extra-reserve",
                user_id=user.id,
                job_id=job.id,
                entry_type="reserve",
                reserved_delta=3,
                idempotency_key="extra-reserve",
            ),
            database.TrialLedgerEntry(
                id="extra-release",
                user_id=user.id,
                job_id=job.id,
                entry_type="release",
                reserved_delta=-3,
                idempotency_key="extra-release",
            ),
        ]
    )
    db.commit()

    with pytest.raises(TrialStateError, match="lifecycle"):
        service.consume(job.id)

    assert len(entries(db, user.id)) == 5


@pytest.mark.parametrize("status", ["pending", "reserved", "released", "failed"])
def test_consume_rejects_illegal_lifecycle(db, status):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, status=status)

    with pytest.raises(TrialStateError):
        service.consume(job.id)


def test_release_succeeds_and_is_idempotent(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=5)
    service.reserve(user.id, job.id, 5, "reserve")

    expected = service.release(job.id, "renderer failed")

    assert expected == TrialBalance(200, 0, 0, 200)
    stored = db.get(database.RemediationJob, job.id)
    assert stored.status == "released"
    assert stored.failure_reason == "renderer failed"
    assert isinstance(stored.completed_at, datetime)
    assert service.release(job.id, "renderer failed") == expected
    assert entries(db, user.id)[-1].idempotency_key == f"release:{job.id}"


def test_release_retry_rejects_extra_reserve_consume_pair(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=3)
    service.reserve(user.id, job.id, 3, "reserve")
    service.release(job.id, "renderer failed")
    db.add_all(
        [
            database.TrialLedgerEntry(
                id="extra-reserve",
                user_id=user.id,
                job_id=job.id,
                entry_type="reserve",
                reserved_delta=3,
                idempotency_key="extra-reserve",
            ),
            database.TrialLedgerEntry(
                id="extra-consume",
                user_id=user.id,
                job_id=job.id,
                entry_type="consume",
                reserved_delta=-3,
                consumed_delta=3,
                idempotency_key="extra-consume",
            ),
        ]
    )
    db.commit()

    with pytest.raises(TrialStateError, match="lifecycle"):
        service.release(job.id, "renderer failed")

    assert len(entries(db, user.id)) == 5


def test_release_rejects_succeeded_or_reason_conflict(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=2)
    service.reserve(user.id, job.id, 2, "reserve")
    service.release(job.id, "first reason")

    with pytest.raises(TrialStateError, match="reason"):
        service.release(job.id, "different reason")

    succeeded = add_job(db, user, "job-2", 1, status="succeeded")
    with pytest.raises(TrialStateError):
        service.release(succeeded.id, "too late")


def test_transition_rolls_back_ledger_and_job_on_database_failure(db):
    user = add_user(db)
    service = TrialService(db)
    service.ensure_account(user)
    job = add_job(db, user, pages=2)

    def reject_reserve(_mapper, _connection, entry):
        if entry.entry_type == "reserve":
            raise RuntimeError("injected database failure")

    event.listen(database.TrialLedgerEntry, "before_insert", reject_reserve)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            service.reserve(user.id, job.id, 2, "reserve")
    finally:
        event.remove(database.TrialLedgerEntry, "before_insert", reject_reserve)

    assert db.get(database.RemediationJob, job.id).status == "pending"
    assert len(entries(db, user.id)) == 1


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not configured"
)
def test_postgresql_concurrent_reservations_cannot_overspend():
    """The account row lock serializes quota decisions on PostgreSQL."""
    import psycopg

    database_url = os.environ["TEST_DATABASE_URL"]
    psycopg_url = database_url.replace("postgresql+psycopg://", "postgresql://")
    schema = f"trial_service_{uuid4().hex}"
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        connection.execute(f'create schema "{schema}"')

    engine = create_engine(
        database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    database.Base.metadata.create_all(engine)
    seed = factory()
    try:
        user = add_user(seed)
        TrialService(seed).ensure_account(user)
        add_job(seed, user, "job-1", 150)
        add_job(seed, user, "job-2", 150)
    finally:
        seed.close()

    barrier = threading.Barrier(2)

    def reserve(job_id):
        session = factory()
        try:
            barrier.wait()
            return TrialService(session).reserve(
                "user-1", job_id, 150, f"reserve:{job_id}"
            )
        except InsufficientPages:
            return "insufficient"
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(reserve, ("job-1", "job-2")))
        assert sum(isinstance(result, TrialBalance) for result in results) == 1
        assert results.count("insufficient") == 1
    finally:
        engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(f'drop schema "{schema}" cascade')
