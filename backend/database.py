"""
SQL Database Models and Connections for the WCAG Platform.
"""
from datetime import datetime
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from .config import settings

# Create engine. Connect args only needed for SQLite.
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """User representation representing an authenticated SSO entity."""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True)  # OIDC subject ID
    email = Column(String, unique=True, index=True)
    name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    files = relationship("UploadedFile", back_populates="owner", cascade="all, delete-orphan")
    trial_account = relationship(
        "TrialAccount",
        back_populates="user",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
    )
    trial_ledger_entries = relationship(
        "TrialLedgerEntry", back_populates="user", cascade="all, delete-orphan"
    )
    remediation_jobs = relationship(
        "RemediationJob", back_populates="user", cascade="all, delete-orphan"
    )


class UploadedFile(Base):
    """Uploaded HTML or PDF file metadata."""
    __tablename__ = "uploaded_files"
    
    id = Column(String, primary_key=True, index=True)  # UUID
    filename = Column(String)
    file_type = Column(String)
    file_path = Column(String)
    file_size = Column(Integer)
    page_count = Column(Integer, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)  # Allow anonymous in debug/demo mode
    
    owner = relationship("User", back_populates="files")
    reports = relationship("AccessibilityReport", back_populates="file", cascade="all, delete-orphan")
    remediation_jobs = relationship(
        "RemediationJob", back_populates="file", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "page_count IS NULL OR page_count >= 0",
            name="ck_uploaded_files_page_count_nonnegative",
        ),
    )


class AccessibilityReport(Base):
    """WCAG 2.2 analysis report metadata and full JSON response."""
    __tablename__ = "accessibility_reports"
    
    id = Column(String, primary_key=True, index=True)  # UUID
    file_id = Column(String, ForeignKey("uploaded_files.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    report_json = Column(Text)  # Serialized AccessibilityReport model
    
    file = relationship("UploadedFile", back_populates="reports")
    remediation_jobs = relationship("RemediationJob", back_populates="report")


class TrialAccount(Base):
    """Immutable provenance for the one trial grant associated with a user."""

    __tablename__ = "trial_accounts"

    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    normalized_email = Column(String, nullable=False)
    normalized_domain = Column(String, nullable=False)
    granted_pages = Column(Integer, nullable=False)
    eligibility_rule_version = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="trial_account")

    __table_args__ = (
        CheckConstraint(
            "granted_pages >= 0", name="ck_trial_accounts_granted_pages_nonnegative"
        ),
        CheckConstraint(
            "normalized_email = lower(trim(normalized_email))",
            name="ck_trial_accounts_normalized_email",
        ),
        CheckConstraint(
            "normalized_domain = lower(trim(normalized_domain))",
            name="ck_trial_accounts_normalized_domain",
        ),
    )


@event.listens_for(TrialAccount, "before_update")
def prevent_trial_grant_provenance_update(_mapper, _connection, account):
    """Keep the original grant amount and rule version as audit evidence."""
    state = inspect(account)
    if (
        state.attrs.granted_pages.history.has_changes()
        or state.attrs.eligibility_rule_version.history.has_changes()
    ):
        raise ValueError("trial account grant provenance is immutable")


class TrialLedgerEntry(Base):
    """Append-only-style signed deltas used to derive a user's trial balance."""

    __tablename__ = "trial_ledger_entries"

    id = Column(String, primary_key=True)
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id = Column(
        String, ForeignKey("remediation_jobs.id", ondelete="SET NULL"), nullable=True
    )
    entry_type = Column(String, nullable=False)
    granted_delta = Column(Integer, nullable=False, default=0)
    reserved_delta = Column(Integer, nullable=False, default=0)
    consumed_delta = Column(Integer, nullable=False, default=0)
    idempotency_key = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user = relationship("User", back_populates="trial_ledger_entries")
    job = relationship("RemediationJob", back_populates="ledger_entries")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_trial_ledger_user_idempotency"
        ),
        CheckConstraint(
            "entry_type IN ('grant', 'reserve', 'consume', 'release')",
            name="ck_trial_ledger_entry_type",
        ),
        Index("ix_trial_ledger_entries_job_id", "job_id"),
    )


class RemediationJob(Base):
    """Durable lifecycle record for one trial remediation operation."""

    __tablename__ = "remediation_jobs"

    id = Column(String, primary_key=True)
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    file_id = Column(
        String, ForeignKey("uploaded_files.id", ondelete="CASCADE"), nullable=False
    )
    report_id = Column(
        String,
        ForeignKey("accessibility_reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String, nullable=False)
    page_count = Column(Integer, nullable=False)
    idempotency_key = Column(String, nullable=False)
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="remediation_jobs")
    file = relationship("UploadedFile", back_populates="remediation_jobs")
    report = relationship("AccessibilityReport", back_populates="remediation_jobs")
    ledger_entries = relationship("TrialLedgerEntry", back_populates="job")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_remediation_jobs_user_idempotency"
        ),
        CheckConstraint(
            "status IN ('pending', 'reserved', 'processing', 'succeeded', 'failed', 'released')",
            name="ck_remediation_jobs_status",
        ),
        CheckConstraint(
            "page_count >= 0", name="ck_remediation_jobs_page_count_nonnegative"
        ),
        Index("ix_remediation_jobs_file_id", "file_id"),
        Index("ix_remediation_jobs_report_id", "report_id"),
        Index("ix_remediation_jobs_status", "status"),
    )


def init_db():
    """Create all tables in the database."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency provider for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
