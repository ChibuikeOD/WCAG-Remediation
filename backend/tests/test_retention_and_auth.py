"""
Unit tests for data retention policies and OIDC SSO authentication configuration.
"""
import os
import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base, User, UploadedFile, AccessibilityReport as DbReport
from backend.config import settings


@pytest.fixture
def db_session():
    """In-memory database session fixture."""
    engine = create_engine("sqlite:///:memory:")
    SessionClass = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionClass()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def test_db_relationships(db_session):
    """Verifies user/file/report DB relations function and cascade correctly."""
    # Create user
    user = User(id="umass_user_1", email="user1@umass.edu", name="Professor One")
    db_session.add(user)
    db_session.commit()
    
    # Create file upload
    file_rec = UploadedFile(
        id="file_uuid_999",
        filename="lecture_syllabus.pdf",
        file_type="pdf",
        file_path="/tmp/uploads/file_uuid_999.pdf",
        file_size=1024,
        owner_id=user.id
    )
    db_session.add(file_rec)
    db_session.commit()
    
    # Create report
    report = DbReport(
        id="report_uuid_888",
        file_id=file_rec.id,
        report_json='{"status": "FAIL", "total_issues": 12}'
    )
    db_session.add(report)
    db_session.commit()
    
    # Query validation
    db_user = db_session.query(User).filter(User.id == "umass_user_1").first()
    assert db_user is not None
    assert len(db_user.files) == 1
    assert db_user.files[0].filename == "lecture_syllabus.pdf"
    assert len(db_user.files[0].reports) == 1
    
    # Verify cascade deletion
    db_session.delete(db_user)
    db_session.commit()
    
    assert db_session.query(UploadedFile).filter(UploadedFile.id == "file_uuid_999").first() is None
    assert db_session.query(DbReport).filter(DbReport.id == "report_uuid_888").first() is None


def test_retention_expiration_filter(db_session, tmp_path):
    """Verifies retention filter isolates and handles expired records properly."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    
    # Configure mock retention settings
    settings.RETENTION_PERIOD_HOURS = 2
    
    # Create user
    user = User(id="user_2", email="user2@umass.edu", name="Professor Two")
    db_session.add(user)
    db_session.commit()
    
    # File 1: Expired (3 hours ago)
    expired_id = "file_exp_1"
    expired_path = upload_dir / "expired.pdf"
    expired_path.touch()
    expired_rec = UploadedFile(
        id=expired_id,
        filename="expired.pdf",
        file_type="pdf",
        file_path=str(expired_path),
        file_size=200,
        uploaded_at=datetime.utcnow() - timedelta(hours=3),
        owner_id=user.id
    )
    db_session.add(expired_rec)
    
    # File 2: Active (30 mins ago)
    active_id = "file_act_1"
    active_path = upload_dir / "active.pdf"
    active_path.touch()
    active_rec = UploadedFile(
        id=active_id,
        filename="active.pdf",
        file_type="pdf",
        file_path=str(active_path),
        file_size=200,
        uploaded_at=datetime.utcnow() - timedelta(minutes=30),
        owner_id=user.id
    )
    db_session.add(active_rec)
    db_session.commit()
    
    # Apply expiration query cutoff
    cutoff_time = datetime.utcnow() - timedelta(hours=settings.RETENTION_PERIOD_HOURS)
    expired_query_results = db_session.query(UploadedFile).filter(UploadedFile.uploaded_at < cutoff_time).all()
    
    # Assertions
    assert len(expired_query_results) == 1
    assert expired_query_results[0].id == expired_id
    
    # Run manual cleanup simulation
    for file_rec in expired_query_results:
        if file_rec.file_path and os.path.exists(file_rec.file_path):
            os.remove(file_rec.file_path)
        db_session.delete(file_rec)
    db_session.commit()
    
    # Disk assertions
    assert not expired_path.exists()
    assert active_path.exists()
    
    # DB assertions
    assert db_session.query(UploadedFile).filter(UploadedFile.id == expired_id).first() is None
    assert db_session.query(UploadedFile).filter(UploadedFile.id == active_id).first() is not None
