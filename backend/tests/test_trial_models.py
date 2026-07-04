"""Persistence and relationship tests for the durable trial ledger schema."""

from datetime import datetime

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


def test_trial_account_grant_provenance_is_immutable(db_session):
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

    account.granted_pages = 20
    with pytest.raises(ValueError, match="grant provenance is immutable"):
        db_session.commit()
    db_session.rollback()

    account.eligibility_rule_version = "changed"
    with pytest.raises(ValueError, match="grant provenance is immutable"):
        db_session.commit()


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


@pytest.mark.parametrize("entry_type", ["grant", "reserve", "consume", "release"])
def test_trial_ledger_entry_allows_supported_types(db_session, entry_type):
    user = add_user(db_session)
    db_session.add(
        database.TrialLedgerEntry(
            id=f"ledger-{entry_type}",
            user=user,
            entry_type=entry_type,
            granted_delta=0,
            reserved_delta=0,
            consumed_delta=0,
            idempotency_key=entry_type,
        )
    )
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


def test_deleting_user_cascades_all_user_owned_trial_data(db_session):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    account = database.TrialAccount(
        user=user,
        normalized_email="person@example.com",
        normalized_domain="example.com",
        granted_pages=10,
        eligibility_rule_version="v1",
    )
    job = database.RemediationJob(
        id="job-1",
        user=user,
        file=uploaded_file,
        status="reserved",
        page_count=2,
        idempotency_key="job-1",
    )
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
    db_session.add_all([account, job, ledger])
    db_session.commit()

    db_session.delete(user)
    db_session.commit()

    assert db_session.get(database.TrialAccount, user.id) is None
    assert db_session.get(database.TrialLedgerEntry, ledger.id) is None
    assert db_session.get(database.RemediationJob, job.id) is None


def test_deleting_job_preserves_ledger_history_and_clears_job_link(db_session):
    user = add_user(db_session)
    uploaded_file = add_file(db_session, user)
    job = database.RemediationJob(
        id="job-1",
        user=user,
        file=uploaded_file,
        status="released",
        page_count=2,
        idempotency_key="job-1",
    )
    ledger = database.TrialLedgerEntry(
        id="ledger-1",
        user=user,
        job=job,
        entry_type="release",
        granted_delta=0,
        reserved_delta=-2,
        consumed_delta=0,
        idempotency_key="release-job-1",
    )
    db_session.add_all([job, ledger])
    db_session.commit()

    db_session.delete(job)
    db_session.commit()

    assert db_session.get(database.TrialLedgerEntry, ledger.id).job_id is None


def test_deleting_uploaded_file_cascades_its_remediation_jobs(db_session):
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

    db_session.delete(uploaded_file)
    db_session.commit()

    assert db_session.get(database.RemediationJob, job.id) is None
