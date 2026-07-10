from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.processing_job import ProcessingJob


def start_job(db: Session, document_id: str, job_type: str) -> ProcessingJob:
    job = ProcessingJob(
        document_id=document_id,
        job_type=job_type,
        status="RUNNING",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def complete_job(db: Session, job: ProcessingJob, result_summary: str) -> None:
    job.status = "COMPLETED"
    job.completed_at = datetime.utcnow()
    job.result_summary = result_summary
    db.commit()


def fail_job(db: Session, job: ProcessingJob, error_message: str) -> None:
    job.status = "FAILED"
    job.completed_at = datetime.utcnow()
    job.error_message = error_message[:500]
    db.commit()
