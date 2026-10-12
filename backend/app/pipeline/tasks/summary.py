import logging

from app.pipeline.celery_app import celery_app

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM_PROMPT = (
    "당신은 문서를 간결하게 요약하는 어시스턴트입니다. "
    "아래 문서 내용을 읽고, 핵심 주제와 주요 내용을 요약하세요. "
    "문서에 없는 내용을 추측해서 덧붙이지 마세요. "
    "반드시 한국어(한글)로만 작성하세요. 중국어(한자)나 영어 문장으로 작성하는 것은 금지됩니다. "
    "You must respond only in Korean (Hangul). Never respond in Chinese."
)

# Qwen (Chinese-origin model) sometimes drifts into Chinese despite the Korean
# instruction. Detect by CJK-Han character ratio and retry once with the
# instruction repeated in the user turn.
_MAX_HAN_RATIO = 0.05


def _han_ratio(text: str) -> float:
    import re

    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    return len(re.findall(r"[一-鿿]", stripped)) / len(stripped)

# Local model context budget: the shared LocalLLMProvider isn't given a large
# max_new_tokens for summarization, and feeding it the entire document (up to
# 200k chars) would blow past the 3B model's practical prompt window and slow
# generation for every auto-triggered summary. Truncate to a size that keeps
# latency reasonable while still covering most short-to-medium reports.
_MAX_SUMMARY_INPUT_CHARS = 12_000

_SUMMARY_MODEL_KEY = "qwen2.5-3b"


@celery_app.task(name="tasks.generate_summary", queue="embed")
def generate_summary(document_id: str) -> dict:
    from app.db.models.document import Document
    from app.db.session import get_sync_db
    from app.services.llm import get_llm_provider

    db = get_sync_db()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return {"document_id": document_id, "status": "NOT_FOUND"}

        text = (doc.parsed_text or "").strip()
        if not text:
            doc.summary = None
            doc.summary_status = "FAILED"
            db.commit()
            return {"document_id": document_id, "status": "FAILED", "reason": "empty text"}

        doc.summary_status = "GENERATING"
        db.commit()

        truncated = text[:_MAX_SUMMARY_INPUT_CHARS]
        provider = get_llm_provider(_SUMMARY_MODEL_KEY)
        summary = provider.generate(
            _SUMMARY_SYSTEM_PROMPT,
            [{"role": "user", "content": f"다음 문서를 한국어로 요약하세요:\n\n{truncated}"}],
        )

        if _han_ratio(summary) > _MAX_HAN_RATIO:
            logger.warning(
                "summary drifted to Chinese; retrying once",
                extra={"document_id": document_id, "han_ratio": round(_han_ratio(summary), 3)},
            )
            summary = provider.generate(
                _SUMMARY_SYSTEM_PROMPT,
                [
                    {
                        "role": "user",
                        "content": (
                            "다음 문서를 요약하세요. 반드시 한국어(한글)로만 작성하세요. "
                            f"중국어(한자) 사용 금지.\n\n{truncated}"
                        ),
                    }
                ],
            )

        doc.summary = summary.strip()
        doc.summary_status = "DONE"
        db.commit()

        # 메타 정보 생성 설계서(2026-07-23) Phase 5 — Summary Index. 실패해도
        # 요약 자체는 이미 저장됐으므로 이 문서의 처리 결과를 되돌리지 않는다
        # (best-effort, Qdrant 장애가 요약 생성 자체를 실패시키면 안 됨).
        try:
            from app.services.summary_index import index_document_summary

            index_document_summary(document_id, doc.summary)
        except Exception:
            logger.exception("summary index upsert failed", extra={"document_id": document_id})

        return {"document_id": document_id, "status": "DONE"}

    except Exception as exc:
        logger.exception("generate_summary failed", extra={"document_id": document_id})
        db.rollback()
        try:
            doc = db.get(Document, document_id)
            if doc:
                doc.summary_status = "FAILED"
                db.commit()
        except Exception:
            logger.exception(
                "generate_summary: failed to record failure state",
                extra={"document_id": document_id},
            )
        return {"document_id": document_id, "status": "FAILED", "error": str(exc)}
    finally:
        db.close()
