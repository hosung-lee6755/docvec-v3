from datetime import datetime

from app.pipeline.celery_app import celery_app


@celery_app.task(name="tasks.ingest_document", queue="high")
def ingest_document(document_id: str) -> str:
    from app.db.models.document import Document
    from app.db.session import get_sync_db
    from app.pipeline.job_tracker import complete_job, fail_job, start_job

    db = get_sync_db()
    job = start_job(db, document_id, "INGEST")
    try:
        doc = db.get(Document, document_id)
        if doc:
            doc.status = "INGESTING"
            doc.updated_at = datetime.utcnow()
            db.commit()
            complete_job(db, job, f"파일 수신 확인 ({doc.file_size:,} bytes)")
        else:
            fail_job(db, job, "Document not found")
    except Exception as exc:
        fail_job(db, job, str(exc))
        raise
    finally:
        db.close()

    return document_id
