"""
SQL Database Models and Connections for the WCAG Platform.
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, DateTime, ForeignKey, Text
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


class UploadedFile(Base):
    """Uploaded HTML or PDF file metadata."""
    __tablename__ = "uploaded_files"
    
    id = Column(String, primary_key=True, index=True)  # UUID
    filename = Column(String)
    file_type = Column(String)
    file_path = Column(String)
    file_size = Column(Integer)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)  # Allow anonymous in debug/demo mode
    
    owner = relationship("User", back_populates="files")
    reports = relationship("AccessibilityReport", back_populates="file", cascade="all, delete-orphan")


class AccessibilityReport(Base):
    """WCAG 2.2 analysis report metadata and full JSON response."""
    __tablename__ = "accessibility_reports"
    
    id = Column(String, primary_key=True, index=True)  # UUID
    file_id = Column(String, ForeignKey("uploaded_files.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    report_json = Column(Text)  # Serialized AccessibilityReport model
    
    file = relationship("UploadedFile", back_populates="reports")


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
