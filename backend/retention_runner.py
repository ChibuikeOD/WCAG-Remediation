"""
Data Retention Runner for the WCAG Platform.
Scans and cleans up uploaded files and output files older than RETENTION_PERIOD_HOURS.
"""
import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .config import settings
from .database import SessionLocal, UploadedFile

logger = logging.getLogger(__name__)


async def clean_expired_documents():
    """
    Infinite async loop running the cleanup query.
    Executes once every hour.
    """
    logger.info("Starting Data Retention Runner...")
    logger.info(f"Configured retention period: {settings.RETENTION_PERIOD_HOURS} hours")
    
    while True:
        try:
            # We open a dedicated session for each execution cycle
            db: Session = SessionLocal()
            try:
                cutoff_time = datetime.utcnow() - timedelta(hours=settings.RETENTION_PERIOD_HOURS)
                
                # Fetch files uploaded before the cutoff
                expired_files = db.query(UploadedFile).filter(UploadedFile.uploaded_at < cutoff_time).all()
                
                if expired_files:
                    logger.info(f"Retention Runner: Found {len(expired_files)} expired files to clean up.")
                    
                    for file_rec in expired_files:
                        # 1. Delete original uploaded file from disk
                        if file_rec.file_path and os.path.exists(file_rec.file_path):
                            try:
                                os.remove(file_rec.file_path)
                                logger.info(f"Deleted original upload: {file_rec.file_path}")
                            except Exception as e:
                                logger.error(f"Error deleting file {file_rec.file_path}: {e}")
                        
                        # 2. Delete any output files referenced in associated reports
                        for report_rec in file_rec.reports:
                            try:
                                if report_rec.report_json:
                                    report_data = json.loads(report_rec.report_json)
                                    
                                    # Remediated file deletion
                                    rem_file_path = report_data.get("remediated_file_path")
                                    if rem_file_path and os.path.exists(rem_file_path):
                                        os.remove(rem_file_path)
                                        logger.info(f"Deleted remediated output file: {rem_file_path}")
                                    
                                    # Remediation report deletion
                                    rem_report_path = report_data.get("remediation_report_path")
                                    if rem_report_path and os.path.exists(rem_report_path):
                                        os.remove(rem_report_path)
                                        logger.info(f"Deleted remediation report: {rem_report_path}")
                            except Exception as e:
                                logger.error(f"Error reading report details for cleanup: {e}")
                        
                        # 3. Delete database records (cascade-deletes the reports)
                        db.delete(file_rec)
                    
                    db.commit()
                    logger.info("Retention Runner: Successfully cleared expired files and records.")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in Retention Runner cycle: {e}")
            
        # Run cleanup once per hour
        await asyncio.sleep(3600)
