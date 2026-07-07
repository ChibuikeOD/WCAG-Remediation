"""
SQL Database Models and Connections for the WCAG Platform.
"""
from datetime import datetime, timezone
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    inspect,
    select,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from .config import settings

# Create engine. Connect args only needed for SQLite.
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def utc_now():
    """Return an aware UTC timestamp for ORM-side timestamp defaults."""
    return datetime.now(timezone.utc)


class User(Base):
    """User representation representing an authenticated SSO entity."""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True)  # OIDC subject ID
    email = Column(String, unique=True, index=True)
    name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    files = relationship(
        "UploadedFile", back_populates="owner", cascade="all, delete-orphan"
    )
    trial_account = relationship(
        "TrialAccount",
        back_populates="user",
        cascade="save-update, merge",
        passive_deletes="all",
        single_parent=True,
        uselist=False,
    )
    trial_ledger_entries = relationship(
        "TrialLedgerEntry", back_populates="user", passive_deletes="all"
    )
    remediation_jobs = relationship(
        "RemediationJob", back_populates="user", passive_deletes="all"
    )
    credit_purchases = relationship(
        "CreditPurchase", back_populates="user", passive_deletes="all"
    )
    institutional_invoice_requests = relationship(
        "InstitutionalInvoiceRequest",
        back_populates="user",
        passive_deletes="all",
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
    owner_id = Column(
        String,
        ForeignKey(
            "users.id", name="fk_uploaded_files_owner_id_users", ondelete="CASCADE"
        ),
        nullable=True,
    )  # Allow anonymous in debug/demo mode
    
    owner = relationship("User", back_populates="files")
    reports = relationship("AccessibilityReport", back_populates="file", cascade="all, delete-orphan")
    remediation_jobs = relationship(
        "RemediationJob",
        back_populates="file",
        cascade="save-update, merge",
        passive_deletes="all",
        overlaps="remediation_jobs,user",
    )

    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_uploaded_files_id_owner_id"),
        CheckConstraint(
            "page_count IS NULL OR page_count >= 0",
            name="ck_uploaded_files_page_count_nonnegative",
        ),
    )


@event.listens_for(UploadedFile, "before_update")
def prevent_uploaded_file_owner_update(_mapper, _connection, uploaded_file):
    """Keep file ownership fixed after the file row is inserted."""
    if inspect(uploaded_file).attrs.owner_id.history.has_changes():
        raise ValueError("uploaded file owner is immutable")


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
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

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
    immutable_fields = (
        "user_id",
        "normalized_email",
        "normalized_domain",
        "granted_pages",
        "eligibility_rule_version",
        "created_at",
    )
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError("trial account eligibility provenance is immutable")


class TrialLedgerEntry(Base):
    """Append-only-style signed deltas used to derive a user's trial balance."""

    __tablename__ = "trial_ledger_entries"

    id = Column(String, primary_key=True)
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id = Column(String, nullable=True)
    entry_type = Column(String, nullable=False)
    granted_delta = Column(Integer, nullable=False, default=0)
    reserved_delta = Column(Integer, nullable=False, default=0)
    consumed_delta = Column(Integer, nullable=False, default=0)
    idempotency_key = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

    user = relationship("User", back_populates="trial_ledger_entries")
    job = relationship(
        "RemediationJob",
        back_populates="ledger_entries",
        overlaps="trial_ledger_entries,user",
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_trial_ledger_user_idempotency"
        ),
        ForeignKeyConstraint(
            ["job_id", "user_id"],
            ["remediation_jobs.id", "remediation_jobs.user_id"],
            name="fk_trial_ledger_job_owner",
        ),
        CheckConstraint(
            "entry_type IN ('grant', 'purchase', 'reserve', 'consume', 'release')",
            name="ck_trial_ledger_entry_type",
        ),
        CheckConstraint(
            "(entry_type = 'grant' AND granted_delta > 0 "
            "AND reserved_delta = 0 AND consumed_delta = 0 AND job_id IS NULL) OR "
            "(entry_type = 'purchase' AND granted_delta > 0 "
            "AND reserved_delta = 0 AND consumed_delta = 0 AND job_id IS NULL) OR "
            "(entry_type = 'reserve' AND granted_delta = 0 "
            "AND reserved_delta > 0 AND consumed_delta = 0 AND job_id IS NOT NULL) OR "
            "(entry_type = 'release' AND granted_delta = 0 "
            "AND reserved_delta < 0 AND consumed_delta = 0 AND job_id IS NOT NULL) OR "
            "(entry_type = 'consume' AND granted_delta = 0 "
            "AND reserved_delta < 0 AND consumed_delta > 0 "
            "AND consumed_delta = -reserved_delta AND job_id IS NOT NULL)",
            name="ck_trial_ledger_signed_deltas",
        ),
        Index("ix_trial_ledger_entries_job_id", "job_id"),
    )


@event.listens_for(TrialLedgerEntry, "before_update")
@event.listens_for(TrialLedgerEntry, "before_delete")
def prevent_trial_ledger_mutation(_mapper, _connection, _entry):
    """Reject ORM mutation of the append-only trial ledger."""
    raise ValueError("trial ledger entries are append-only")


class RemediationJob(Base):
    """Durable lifecycle record for one trial remediation operation."""

    __tablename__ = "remediation_jobs"

    id = Column(String, primary_key=True)
    user_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Ownership is validated by an ORM guard and a PostgreSQL trigger. A composite
    # FK cannot SET NULL only file_id portably, so the retention-safe FK is singular.
    file_id = Column(
        String, ForeignKey("uploaded_files.id", ondelete="SET NULL"), nullable=True
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
    output_artifact_key = Column(String, nullable=True)
    report_artifact_key = Column(String, nullable=True)
    response_json = Column(Text, nullable=True)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship(
        "User", back_populates="remediation_jobs", overlaps="remediation_jobs"
    )
    file = relationship(
        "UploadedFile",
        back_populates="remediation_jobs",
        overlaps="remediation_jobs,user",
    )
    report = relationship("AccessibilityReport", back_populates="remediation_jobs")
    ledger_entries = relationship(
        "TrialLedgerEntry",
        back_populates="job",
        overlaps="trial_ledger_entries,user",
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_remediation_jobs_user_idempotency"
        ),
        UniqueConstraint("id", "user_id", name="uq_remediation_jobs_id_user_id"),
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


class CreditPurchase(Base):
    """A Stripe-backed credit purchase or sales-assisted institutional plan."""

    __tablename__ = "credit_purchases"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purchase_type = Column(String, nullable=False)
    catalog_key = Column(String, nullable=False)
    service_mode = Column(String, nullable=False)
    pages_included = Column(Integer, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="usd")
    status = Column(String, nullable=False)
    stripe_checkout_session_id = Column(String, unique=True, nullable=True)
    stripe_payment_intent_id = Column(String, nullable=True)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, unique=True, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    fulfilled_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="credit_purchases")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "stripe_checkout_session_id",
            name="uq_credit_purchases_user_stripe_session",
        ),
        CheckConstraint(
            "purchase_type IN ('credit_pack', 'institutional_plan', 'subscription_plan')",
            name="ck_credit_purchases_type",
        ),
        CheckConstraint(
            "service_mode IN ('remediation', 'audit')",
            name="ck_credit_purchases_service_mode",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'fulfilled', 'invoice_requested', 'invoice_sent', 'paid', 'past_due', 'canceled', 'void')",
            name="ck_credit_purchases_status",
        ),
        CheckConstraint("pages_included > 0", name="ck_credit_purchases_pages_positive"),
        CheckConstraint("amount_cents >= 0", name="ck_credit_purchases_amount_nonnegative"),
        Index("ix_credit_purchases_user_id", "user_id"),
        Index("ix_credit_purchases_status", "status"),
        Index("ix_credit_purchases_stripe_checkout_session_id", "stripe_checkout_session_id"),
        Index("ix_credit_purchases_stripe_subscription_id", "stripe_subscription_id"),
    )


class InstitutionalInvoiceRequest(Base):
    """Sales-assisted invoice/PO request for libraries, campuses, and agencies."""

    __tablename__ = "institutional_invoice_requests"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_key = Column(String, nullable=False)
    service_mode = Column(String, nullable=False)
    organization_name = Column(String, nullable=False)
    contact_name = Column(String, nullable=False)
    contact_email = Column(String, nullable=False)
    normalized_domain = Column(String, nullable=False)
    domain_verified = Column(Integer, nullable=False, default=0)
    po_number = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    pages_included = Column(Integer, nullable=False)
    annual_price_cents = Column(Integer, nullable=False)
    overage_cents = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="requested")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())

    user = relationship("User", back_populates="institutional_invoice_requests")

    __table_args__ = (
        CheckConstraint(
            "service_mode IN ('remediation', 'audit')",
            name="ck_invoice_requests_service_mode",
        ),
        CheckConstraint(
            "status IN ('requested', 'approved', 'invoice_sent', 'paid', 'declined')",
            name="ck_invoice_requests_status",
        ),
        CheckConstraint(
            "domain_verified IN (0, 1)", name="ck_invoice_requests_domain_verified"
        ),
        Index("ix_invoice_requests_user_id", "user_id"),
        Index("ix_invoice_requests_status", "status"),
    )


@event.listens_for(RemediationJob, "before_insert")
@event.listens_for(RemediationJob, "before_update")
def validate_remediation_job_file_owner(_mapper, connection, job):
    """Keep non-null job file links within the job owner's tenant."""
    if job.file_id is None:
        return
    owner_id = connection.execute(
        select(UploadedFile.owner_id).where(UploadedFile.id == job.file_id)
    ).scalar_one_or_none()
    if owner_id != job.user_id:
        raise ValueError("remediation job file must be owned by the job user")


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
