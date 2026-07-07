"""Persistence and relationship tests for the durable trial ledger schema."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend import database


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    database.Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        database.Base.metadata.drop_all(bind=engine)


def add_user(db_session, user_id="user-1"):
    user = database.User(id=user_id, email=f"{user_id}@example.com", name=user_id)
    db_session.add(user)
    db_session.commit()
    return user


def add_file(db_session, user, file_id="file-1", page_count=None):
    uploaded_file = database.UploadedFile(
        id=file_id,
        filename="source.pdf",
        file_type="application/pdf",
        file_path=f"uploads/{file_id}.pdf",
        file_size=123,
        page_count=page_count,
        owner=user,
    )
    db_session.add(uploaded_file)
    db_session.commit()
    return uploaded_file


def add_job(db_session, user, uploaded_file, job_id="job-1"):
    job = database.RemediationJob(
        id=job_id,
        user=user,
        file=uploaded_file,
        status="pending",
        page_count=2,
        idempotency_key=job_id,
    )
    db_session.add(job)
    db_session.commit()
    return job


def test_uploaded_file_owner_reassignment_is_immutable(db_session):
    original_owner = add_user(db_session, "original-owner")
    replacement_owner = add_user(db_session, "replacement-owner")
    uploaded_file = add_file(db_session, original_owner)

    uploaded_file.owner = replacement_owner
    with pytest.raises(ValueError, match="uploaded file owner is immutable"):
        db_session.commit()
    db_session.rollback()

    assert (
        db_session.get(database.UploadedFile, uploaded_file.id).owner_id
        == original_owner.id
    )


def test_persisted_anonymous_uploaded_file_cannot_gain_an_owner(db_session):
    user = add_user(db_session)
    uploaded_file = database.UploadedFile(
        id="anonymous-file",
        filename="source.pdf",
        file_type="application/pdf",
        file_path="uploads/anonymous-file.pdf",
        file_size=123,
        owner_id=None,
    )
    db_session.add(uploaded_file)
    db_session.commit()

    uploaded_file.owner_id = user.id
    with pytest.raises(ValueError, match="uploaded file owner is immutable"):
        db_session.commit()


def test_db_file_storage_does_not_reassign_the_same_owner(db_session, monkeypatch):
    from backend import main

    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    owner_assignments = []

    def record_owner_assignment(_target, value, _old_value, _initiator):
        owner_assignments.append(value)

    event.listen(database.UploadedFile.owner_id, "set", record_owner_assignment)
    monkeypatch.setattr(
        main, "SessionLocal", sessionmaker(bind=db_session.get_bind())
    )
    try:
        main.DbFileStorage()[uploaded_file.id] = {
            "original_filename": "renamed.pdf",
            "file_type": uploaded_file.file_type,
            "file_path": uploaded_file.file_path,
            "file_size": uploaded_file.file_size,
            "uploaded_at": uploaded_file.uploaded_at,
            "owner_id": user.id,
        }
    finally:
        event.remove(database.UploadedFile.owner_id, "set", record_owner_assignment)

    assert owner_assignments == []
    db_session.expire_all()
    assert (
        db_session.get(database.UploadedFile, uploaded_file.id).filename
        == "renamed.pdf"
    )


def test_trial_account_is_one_per_user_and_persists_grant_provenance(db_session):
    user = add_user(db_session)
    account = database.TrialAccount(
        user=user,
        normalized_email="person@example.com",
        normalized_domain="example.com",
        granted_pages=10,
        eligibility_rule_version="2026-07-04",
    )
    db_session.add(account)
    db_session.commit()

    stored = db_session.get(database.TrialAccount, user.id)
    assert stored.normalized_email == "person@example.com"
    assert stored.normalized_domain == "example.com"
    assert stored.granted_pages == 10
    assert stored.eligibility_rule_version == "2026-07-04"
    assert isinstance(stored.created_at, datetime)
    db_session.expunge(stored)

    db_session.add(
        database.TrialAccount(
            user_id=user.id,
            normalized_email="other@example.com",
            normalized_domain="example.com",
            granted_pages=5,
            eligibility_rule_version="later",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize(
    ("attribute", "replacement"),
    [
        ("normalized_email", "changed@example.com"),
        ("normalized_domain", "changed.example"),
        ("granted_pages", 20),
        ("eligibility_rule_version", "changed"),
        ("created_at", datetime(2030, 1, 1, tzinfo=timezone.utc)),
    ],
)
def test_trial_account_eligibility_provenance_is_immutable(
    db_session, attribute, replacement
):
    user = add_user(db_session)
    account = database.TrialAccount(
        user=user,
        normalized_email="person@example.com",
        normalized_domain="example.com",
        granted_pages=10,
        eligibility_rule_version="2026-07-04",
    )
    db_session.add(account)
    db_session.commit()

    setattr(account, attribute, replacement)
    with pytest.raises(ValueError, match="eligibility provenance is immutable"):
        db_session.commit()


def test_trial_account_user_ownership_is_immutable(db_session):
    original_user = add_user(db_session, "original-user")
    replacement_user = add_user(db_session, "replacement-user")
    account = database.TrialAccount(
        user=original_user,
        normalized_email="person@example.com",
        normalized_domain="example.com",
        granted_pages=10,
        eligibility_rule_version="v1",
    )
    db_session.add(account)
    db_session.commit()

    account.user = replacement_user
    with pytest.raises(ValueError, match="eligibility provenance is immutable"):
        db_session.commit()
    db_session.rollback()

    assert db_session.get(database.TrialAccount, original_user.id).user_id == original_user.id
    assert db_session.get(database.TrialAccount, replacement_user.id) is None


def test_trial_ledger_entry_enforces_user_idempotency_and_signed_deltas(db_session):
    user = add_user(db_session)
    first = database.TrialLedgerEntry(
        id="ledger-1",
        user=user,
        entry_type="grant",
        granted_delta=10,
        reserved_delta=0,
        consumed_delta=0,
        idempotency_key="initial-grant",
    )
    db_session.add(first)
    db_session.commit()

    assert db_session.get(database.TrialLedgerEntry, "ledger-1").granted_delta == 10

    db_session.add(
        database.TrialLedgerEntry(
            id="ledger-2",
            user_id=user.id,
            entry_type="release",
            granted_delta=0,
            reserved_delta=-2,
            consumed_delta=0,
            idempotency_key="initial-grant",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize(
    ("entry_type", "granted", "reserved", "consumed"),
    [
        ("grant", 10, 0, 0),
        ("purchase", 10, 0, 0),
        ("reserve", 0, 3, 0),
        ("release", 0, -3, 0),
        ("consume", 0, -3, 3),
    ],
)
def test_trial_ledger_entry_allows_each_legal_signed_delta_form(
    db_session, entry_type, granted, reserved, consumed
):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    job = None if entry_type in {"grant", "purchase"} else add_job(db_session, user, uploaded_file)
    db_session.add(
        database.TrialLedgerEntry(
            id=f"ledger-{entry_type}",
            user=user,
            job=job,
            entry_type=entry_type,
            granted_delta=granted,
            reserved_delta=reserved,
            consumed_delta=consumed,
            idempotency_key=entry_type,
        )
    )
    db_session.commit()


@pytest.mark.parametrize(
    ("entry_type", "granted", "reserved", "consumed", "needs_job"),
    [
        ("grant", 0, 0, 0, False),
        ("grant", -1, 0, 0, False),
        ("grant", 1, 1, 0, False),
        ("purchase", 0, 0, 0, False),
        ("purchase", -1, 0, 0, False),
        ("purchase", 1, 1, 0, False),
        ("reserve", 0, 0, 0, True),
        ("reserve", 0, -1, 0, True),
        ("reserve", 1, 1, 0, True),
        ("release", 0, 1, 0, True),
        ("release", 0, -1, 1, True),
        ("consume", 0, 1, 1, True),
        ("consume", 0, -2, 1, True),
        ("consume", 1, -1, 1, True),
    ],
)
def test_trial_ledger_entry_rejects_each_illegal_signed_delta_form(
    db_session, entry_type, granted, reserved, consumed, needs_job
):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    job = add_job(db_session, user, uploaded_file) if needs_job else None
    db_session.add(
        database.TrialLedgerEntry(
            id="bad-ledger",
            user=user,
            job=job,
            entry_type=entry_type,
            granted_delta=granted,
            reserved_delta=reserved,
            consumed_delta=consumed,
            idempotency_key="bad-ledger",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("entry_type", ["reserve", "release", "consume"])
def test_non_grant_ledger_entries_require_a_job(db_session, entry_type):
    user = add_user(db_session)
    deltas = {
        "reserve": (0, 1, 0),
        "release": (0, -1, 0),
        "consume": (0, -1, 1),
    }
    granted, reserved, consumed = deltas[entry_type]
    db_session.add(
        database.TrialLedgerEntry(
            id=f"jobless-{entry_type}",
            user=user,
            entry_type=entry_type,
            granted_delta=granted,
            reserved_delta=reserved,
            consumed_delta=consumed,
            idempotency_key=f"jobless-{entry_type}",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_remediation_job_persists_ownership_file_state_and_idempotency(db_session):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user, page_count=4)
    job = database.RemediationJob(
        id="job-1",
        user=user,
        file=uploaded_file,
        status="pending",
        page_count=4,
        idempotency_key="remediate-file-1",
    )
    db_session.add(job)
    db_session.commit()

    stored = db_session.get(database.RemediationJob, "job-1")
    assert stored.user_id == user.id
    assert stored.file_id == uploaded_file.id
    assert stored.report_id is None
    assert stored.status == "pending"
    assert stored.page_count == 4
    assert stored.failure_reason is None
    assert isinstance(stored.created_at, datetime)
    assert isinstance(stored.updated_at, datetime)
    assert stored.completed_at is None

    db_session.add(
        database.RemediationJob(
            id="job-2",
            user_id=user.id,
            file_id=uploaded_file.id,
            status="reserved",
            page_count=4,
            idempotency_key="remediate-file-1",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_remediation_job_rejects_a_file_owned_by_another_user(db_session):
    file_owner = add_user(db_session, "file-owner")
    job_owner = add_user(db_session, "job-owner")
    uploaded_file = add_file(db_session, file_owner)

    db_session.add(
        database.RemediationJob(
            id="cross-user-job",
            user_id=job_owner.id,
            file_id=uploaded_file.id,
            status="pending",
            page_count=1,
            idempotency_key="cross-user-job",
        )
    )
    with pytest.raises(ValueError, match="file must be owned by the job user"):
        db_session.commit()


def test_trial_ledger_entry_rejects_a_job_owned_by_another_user(db_session):
    job_owner = add_user(db_session, "job-owner")
    ledger_owner = add_user(db_session, "ledger-owner")
    uploaded_file = add_file(db_session, job_owner)
    job = add_job(db_session, job_owner, uploaded_file)

    db_session.add(
        database.TrialLedgerEntry(
            id="cross-user-ledger",
            user_id=ledger_owner.id,
            job_id=job.id,
            entry_type="reserve",
            granted_delta=0,
            reserved_delta=1,
            consumed_delta=0,
            idempotency_key="cross-user-ledger",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize(
    "status", ["pending", "reserved", "processing", "succeeded", "failed", "released"]
)
def test_remediation_job_allows_supported_statuses(db_session, status):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    db_session.add(
        database.RemediationJob(
            id=f"job-{status}",
            user=user,
            file=uploaded_file,
            status=status,
            page_count=0,
            idempotency_key=status,
        )
    )
    db_session.commit()


def test_trial_models_reject_invalid_types_statuses_and_negative_counts(db_session):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    invalid_rows = [
        database.TrialAccount(
            user_id=user.id,
            normalized_email="person@example.com",
            normalized_domain="example.com",
            granted_pages=-1,
            eligibility_rule_version="v1",
        ),
        database.TrialLedgerEntry(
            id="bad-ledger",
            user_id=user.id,
            entry_type="refund",
            granted_delta=0,
            reserved_delta=0,
            consumed_delta=0,
            idempotency_key="bad-ledger",
        ),
        database.RemediationJob(
            id="bad-job",
            user_id=user.id,
            file_id=uploaded_file.id,
            status="unknown",
            page_count=-1,
            idempotency_key="bad-job",
        ),
    ]

    for row in invalid_rows:
        db_session.add(row)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


def test_uploaded_file_page_count_is_nullable_and_nonnegative(db_session):
    user = add_user(db_session)
    unknown = add_file(db_session, user, "unknown-pages", page_count=None)
    known = add_file(db_session, user, "known-pages", page_count=7)

    assert db_session.get(database.UploadedFile, unknown.id).page_count is None
    assert db_session.get(database.UploadedFile, known.id).page_count == 7

    known.page_count = -1
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_deleting_user_cascades_trial_provenance_and_ledger_without_orm_guards(
    db_session,
):
    user = add_user(db_session)
    account = database.TrialAccount(
        user=user,
        normalized_email="person@example.com",
        normalized_domain="example.com",
        granted_pages=10,
        eligibility_rule_version="v1",
    )
    ledger = database.TrialLedgerEntry(
        id="ledger-1",
        user=user,
        entry_type="grant",
        granted_delta=10,
        reserved_delta=0,
        consumed_delta=0,
        idempotency_key="initial-grant",
    )
    db_session.add_all([account, ledger])
    db_session.commit()
    user_id, ledger_id = user.id, ledger.id

    db_session.delete(user)
    db_session.commit()

    assert db_session.get(database.TrialAccount, user_id) is None
    assert db_session.get(database.TrialLedgerEntry, ledger_id) is None


def test_trial_ledger_entry_rejects_direct_update(db_session):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    job = add_job(db_session, user, uploaded_file)
    ledger = database.TrialLedgerEntry(
        id="ledger-1",
        user=user,
        job=job,
        entry_type="reserve",
        granted_delta=0,
        reserved_delta=2,
        consumed_delta=0,
        idempotency_key="reserve-job-1",
    )
    db_session.add(ledger)
    db_session.commit()

    ledger.reserved_delta = 3
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()


def test_trial_ledger_entry_rejects_direct_delete(db_session):
    user = add_user(db_session)
    ledger = database.TrialLedgerEntry(
        id="ledger-1",
        user=user,
        entry_type="grant",
        granted_delta=10,
        reserved_delta=0,
        consumed_delta=0,
        idempotency_key="initial-grant",
    )
    db_session.add(ledger)
    db_session.commit()

    db_session.delete(ledger)
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()


def test_remediation_job_remains_mutable(db_session):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    job = add_job(db_session, user, uploaded_file)

    job.status = "processing"
    db_session.commit()

    assert db_session.get(database.RemediationJob, job.id).status == "processing"


def test_deleting_uploaded_file_preserves_its_remediation_job(db_session):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    job = database.RemediationJob(
        id="job-1",
        user=user,
        file=uploaded_file,
        status="pending",
        page_count=1,
        idempotency_key="job-1",
    )
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    db_session.delete(uploaded_file)
    db_session.commit()

    stored_job = db_session.get(database.RemediationJob, job_id)
    assert stored_job is not None
    assert stored_job.file_id is None


def test_deleting_uploaded_file_preserves_job_and_immutable_ledger_history(db_session):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    job = add_job(db_session, user, uploaded_file)
    ledger = database.TrialLedgerEntry(
        id="ledger-1",
        user=user,
        job=job,
        entry_type="reserve",
        granted_delta=0,
        reserved_delta=2,
        consumed_delta=0,
        idempotency_key="reserve-job-1",
    )
    db_session.add(ledger)
    db_session.commit()
    job_id, ledger_id = job.id, ledger.id

    db_session.delete(uploaded_file)
    db_session.commit()

    stored_job = db_session.get(database.RemediationJob, job_id)
    stored_ledger = db_session.get(database.TrialLedgerEntry, ledger_id)
    assert stored_job is not None
    assert stored_job.file_id is None
    assert stored_ledger is not None
    assert stored_ledger.job_id == job_id

    stored_ledger.reserved_delta = 3
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()


def test_trial_timestamp_columns_are_timezone_aware_and_nonnullable(db_session):
    trial_timestamp_columns = [
        database.TrialAccount.__table__.c.created_at,
        database.TrialLedgerEntry.__table__.c.created_at,
        database.RemediationJob.__table__.c.created_at,
        database.RemediationJob.__table__.c.updated_at,
        database.RemediationJob.__table__.c.completed_at,
        database.RemediationJob.__table__.c.processing_started_at,
        database.RemediationJob.__table__.c.lease_expires_at,
    ]
    for column in trial_timestamp_columns:
        assert column.type.timezone is True
    for column in trial_timestamp_columns[:4]:
        assert column.nullable is False
        assert column.server_default is not None
    for column in trial_timestamp_columns[4:]:
        assert column.nullable is True

    user = add_user(db_session)
    account = database.TrialAccount(
        user=user,
        normalized_email="person@example.com",
        normalized_domain="example.com",
        granted_pages=10,
        eligibility_rule_version="v1",
    )
    db_session.add(account)
    db_session.commit()
    # SQLite strips timezone offsets; PostgreSQL behavior is covered by the opt-in test.
    assert account.created_at is not None


def test_trial_model_constraints_match_migration_ddl():
    migration = (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "202607040001_trial_core.sql"
    ).read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", migration.lower())

    assert "unique (id, owner_id)" in normalized
    assert "file_id text null references public.uploaded_files(id) on delete set null" in normalized
    assert "remediation_jobs_enforce_file_ownership" in normalized
    assert "unique (id, user_id)" in normalized
    assert "foreign key (job_id, user_id)" in normalized
    assert "references public.remediation_jobs(id, user_id)" in normalized
    assert "constraint ck_trial_ledger_signed_deltas" in normalized
    assert "timestamp with time zone" in normalized
    assert "trial_ledger_entries_append_only" in normalized
    assert "new.user_id is distinct from old.user_id" in normalized
    assert "fk_uploaded_files_owner_id_users" in normalized
    assert "uploaded_files_immutable_owner" in normalized
    for column in (
        "output_artifact_key text null",
        "report_artifact_key text null",
        "response_json text null",
        "processing_started_at timestamp with time zone null",
        "lease_expires_at timestamp with time zone null",
    ):
        assert column in normalized

    for column_name in (
        "output_artifact_key",
        "report_artifact_key",
        "response_json",
        "processing_started_at",
        "lease_expires_at",
    ):
        assert column_name in database.RemediationJob.__table__.c

    job_file_fk = next(iter(database.RemediationJob.__table__.c.file_id.foreign_keys))
    owner_fk = next(iter(database.UploadedFile.__table__.c.owner_id.foreign_keys))
    assert database.RemediationJob.__table__.c.file_id.nullable is True
    assert job_file_fk.ondelete == "SET NULL"
    assert owner_fk.ondelete == "CASCADE"

    model_constraint_names = {
        constraint.name
        for table in (
            database.UploadedFile.__table__,
            database.TrialAccount.__table__,
            database.RemediationJob.__table__,
            database.TrialLedgerEntry.__table__,
        )
        for constraint in table.constraints
        if constraint.name
    }
    migration_constraint_names = set(
        re.findall(r"constraint ([a-z0-9_]+)", normalized)
    )
    assert model_constraint_names <= migration_constraint_names


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not configured"
)
def test_postgresql_trial_migration_constraints_triggers_and_rls():
    import psycopg

    url = os.environ["TEST_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    schema = f"trial_migration_{uuid4().hex}"
    migration = (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "202607040001_trial_core.sql"
    ).read_text(encoding="utf-8")
    migration = migration.replace("public.", f'"{schema}".')
    migration = migration.replace("auth.uid()", "nullif(current_setting('test.user_id', true), '')")
    migration = migration.replace("to authenticated", "to public")

    with psycopg.connect(url, autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'create schema "{schema}"')
            cursor.execute(
                f'create table "{schema}".users (id text primary key);'
                f'create table "{schema}".uploaded_files ('
                "id text primary key, owner_id text null, "
                "constraint legacy_uploaded_files_owner_id_fkey foreign key (owner_id) "
                f'references "{schema}".users(id));'
                f'create table "{schema}".accessibility_reports ('
                "id text primary key)"
            )
            cursor.execute(migration, prepare=False)

            cursor.execute(
                "select confdeltype from pg_constraint "
                "where conrelid = %s::regclass and conname = "
                "'fk_uploaded_files_owner_id_users'",
                (f'"{schema}".uploaded_files',),
            )
            assert cursor.fetchone() == ("c",)

            cursor.execute(
                "select relname, relrowsecurity from pg_class "
                "join pg_namespace on pg_namespace.oid = pg_class.relnamespace "
                "where nspname = %s and relname in "
                "('trial_accounts', 'trial_ledger_entries', 'remediation_jobs') "
                "order by relname",
                (schema,),
            )
            assert cursor.fetchall() == [
                ("remediation_jobs", True),
                ("trial_accounts", True),
                ("trial_ledger_entries", True),
            ]

            cursor.execute(
                "select policyname from pg_policies where schemaname = %s "
                "order by policyname",
                (schema,),
            )
            assert [row[0] for row in cursor.fetchall()] == [
                "Users can view their own remediation jobs",
                "Users can view their own trial account",
                "Users can view their own trial ledger entries",
            ]
            cursor.execute(
                "select trigger_name from information_schema.triggers "
                "where trigger_schema = %s order by trigger_name",
                (schema,),
            )
            trigger_names = {row[0] for row in cursor.fetchall()}
            assert {
                "remediation_jobs_enforce_file_ownership",
                "remediation_jobs_set_updated_at",
                "trial_accounts_immutable_grant_provenance",
                "trial_ledger_entries_append_only",
                "uploaded_files_immutable_owner",
            } <= trigger_names
            cursor.execute(
                "select table_name, column_name, data_type from information_schema.columns "
                "where table_schema = %s and column_name in "
                "('created_at', 'updated_at', 'completed_at') "
                "and table_name in "
                "('trial_accounts', 'trial_ledger_entries', 'remediation_jobs')",
                (schema,),
            )
            assert all(row[2] == "timestamp with time zone" for row in cursor.fetchall())

            cursor.execute(
                f'insert into "{schema}".users values (%s), (%s);'
                f'insert into "{schema}".uploaded_files (id, owner_id) values (%s, %s)',
                ("user-1", "user-2", "file-1", "user-1"),
            )
            cursor.execute(
                f'update "{schema}".uploaded_files set owner_id = %s where id = %s',
                ("user-1", "file-1"),
            )
            with pytest.raises(psycopg.errors.RaiseException):
                with connection.transaction():
                    cursor.execute(
                        f'update "{schema}".uploaded_files set owner_id = %s where id = %s',
                        ("user-2", "file-1"),
                    )
            cursor.execute(
                f'insert into "{schema}".uploaded_files (id, owner_id) values (%s, null)',
                ("anonymous-file",),
            )
            with pytest.raises(psycopg.errors.RaiseException):
                with connection.transaction():
                    cursor.execute(
                        f'update "{schema}".uploaded_files set owner_id = %s where id = %s',
                        ("user-1", "anonymous-file"),
                    )
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                with connection.transaction():
                    cursor.execute(
                        f'insert into "{schema}".remediation_jobs '
                        "(id, user_id, file_id, status, page_count, idempotency_key) "
                        "values ('cross-user-job', 'user-2', 'file-1', "
                        "'pending', 1, 'cross-user-job')"
                    )

            cursor.execute(
                f'insert into "{schema}".remediation_jobs '
                "(id, user_id, file_id, status, page_count, idempotency_key) "
                "values ('job-1', 'user-1', 'file-1', 'pending', 1, 'job-1')"
            )
            with pytest.raises(psycopg.errors.CheckViolation):
                with connection.transaction():
                    cursor.execute(
                        f'insert into "{schema}".trial_ledger_entries '
                        "(id, user_id, entry_type, idempotency_key) "
                        "values ('bad-grant', 'user-1', 'grant', 'bad-grant')"
                    )
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                with connection.transaction():
                    cursor.execute(
                        f'insert into "{schema}".trial_ledger_entries '
                        "(id, user_id, job_id, entry_type, reserved_delta, idempotency_key) "
                        "values ('cross-user-ledger', 'user-2', 'job-1', "
                        "'reserve', 1, 'cross-user-ledger')"
                    )

            cursor.execute(
                f'insert into "{schema}".trial_accounts '
                "(user_id, normalized_email, normalized_domain, granted_pages, "
                "eligibility_rule_version) values "
                "('user-1', 'person@example.com', 'example.com', 10, 'v1')"
            )
            cursor.execute(
                f'insert into "{schema}".trial_ledger_entries '
                "(id, user_id, job_id, entry_type, reserved_delta, idempotency_key) "
                "values ('ledger-1', 'user-1', 'job-1', 'reserve', 1, 'ledger-1')"
            )
            with pytest.raises(psycopg.errors.RaiseException):
                with connection.transaction():
                    cursor.execute(
                        f'update "{schema}".trial_accounts '
                        "set normalized_domain = 'changed.example' where user_id = 'user-1'"
                    )
            with pytest.raises(psycopg.errors.RaiseException):
                with connection.transaction():
                    cursor.execute(
                        f'update "{schema}".trial_accounts '
                        "set user_id = 'user-2' where user_id = 'user-1'"
                    )
            with pytest.raises(psycopg.errors.RaiseException):
                with connection.transaction():
                    cursor.execute(
                        f'update "{schema}".trial_ledger_entries '
                        "set reserved_delta = 2 where id = 'ledger-1'"
                    )
            with pytest.raises(psycopg.errors.RaiseException):
                with connection.transaction():
                    cursor.execute(
                        f'delete from "{schema}".trial_ledger_entries '
                        "where id = 'ledger-1'"
                    )

            cursor.execute(f'delete from "{schema}".uploaded_files where id = %s', ("file-1",))
            cursor.execute(
                f'select file_id from "{schema}".remediation_jobs where id = %s',
                ("job-1",),
            )
            assert cursor.fetchone() == (None,)
            cursor.execute(
                f'select job_id from "{schema}".trial_ledger_entries where id = %s',
                ("ledger-1",),
            )
            assert cursor.fetchone() == ("job-1",)

            cursor.execute(f'delete from "{schema}".users where id = %s', ("user-1",))
            cursor.execute(
                f'select count(*) from "{schema}".trial_ledger_entries '
                "where user_id = 'user-1'"
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                f'insert into "{schema}".uploaded_files (id, owner_id) values (%s, %s)',
                ("file-2", "user-2"),
            )
            cursor.execute(f'delete from "{schema}".users where id = %s', ("user-2",))
            cursor.execute(
                f'select count(*) from "{schema}".uploaded_files where id = %s',
                ("file-2",),
            )
            assert cursor.fetchone()[0] == 0
            connection.rollback()
