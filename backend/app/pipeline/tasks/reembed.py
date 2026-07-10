import logging

from app.core.config import settings
from app.pipeline.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.reembed_collection", queue="low", bind=True)
def reembed_collection(self, collection_id: str, embedding_model: str) -> dict:
    """Re-embeds every chunk of every indexed document in a collection with a
    new embedding model, upserting each point under its existing id so payload
    (disabled/edited/tags/page_number/etc.) and citations keep working
    unchanged — only the vector itself is replaced. Triggered by
    PATCH /collections/{id} when embedding_model changes on a collection that
    already has documents (see collections.py::update_collection).

    All collections share one physical Qdrant collection with a fixed vector
    dimension (see qdrant_service.py/main.py), and only same-dimension models
    are selectable per collection (see collections.py::_SELECTABLE_MODELS) —
    so re-embedding in place is always dimension-safe here and the physical
    Qdrant collection itself never needs to be recreated."""
    from app.db.models.collection import Collection
    from app.db.models.document import Document
    from app.db.session import get_sync_db
    from app.pipeline.job_tracker import complete_job, fail_job, start_job
    from app.services.embedding import get_embedding_provider
    from app.services.qdrant_service import qdrant_service

    db = get_sync_db()
    try:
        collection = db.get(Collection, collection_id)
        if collection is None:
            return {"collection_id": collection_id, "status": "NOT_FOUND"}

        docs = (
            db.query(Document)
            .filter(Document.collection_id == collection_id, Document.status == "INDEXED")
            .all()
        )
        total = len(docs)
        collection.reembed_status = "RUNNING"
        collection.reembed_progress = f"0/{total}"
        db.commit()

        provider = get_embedding_provider(embedding_model)
        failed_filenames: list[str] = []

        for i, doc in enumerate(docs, start=1):
            job = start_job(db, str(doc.id), "REEMBED")
            try:
                hits = qdrant_service.scroll_by_document(str(doc.id))
                if hits:
                    texts = [h["payload"].get("text", "") for h in hits]
                    vectors = provider.embed(texts)
                    qdrant_service.upsert_points(
                        settings.qdrant_collection_name,
                        [
                            {"id": h["id"], "vector": vector, "payload": h["payload"]}
                            for h, vector in zip(hits, vectors)
                        ],
                    )
                complete_job(db, job, f"{len(hits)}개 청크를 '{embedding_model}' 모델로 재임베딩했습니다")
            except Exception as exc:
                logger.exception(
                    "reembed_collection: document failed",
                    extra={"collection_id": collection_id, "document_id": str(doc.id)},
                )
                fail_job(db, job, str(exc))
                failed_filenames.append(doc.original_filename)

            collection.reembed_progress = f"{i}/{total}"
            db.commit()

        if failed_filenames:
            collection.reembed_status = "FAILED"
            collection.reembed_progress = (
                f"{total - len(failed_filenames)}/{total} 완료, "
                f"{len(failed_filenames)}개 실패: {', '.join(failed_filenames[:5])}"
            )
        else:
            collection.reembed_status = "COMPLETED"
        db.commit()

        return {
            "collection_id": collection_id,
            "status": collection.reembed_status,
            "total": total,
            "failed": failed_filenames,
        }
    except Exception as exc:
        logger.exception("reembed_collection failed", extra={"collection_id": collection_id})
        try:
            collection = db.get(Collection, collection_id)
            if collection:
                collection.reembed_status = "FAILED"
                collection.reembed_progress = str(exc)[:50]
                db.commit()
        except Exception:
            logger.exception("reembed_collection: failed to record failure state")
        return {"collection_id": collection_id, "status": "FAILED", "error": str(exc)}
    finally:
        db.close()
