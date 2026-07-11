import logging
import re

from app.pipeline.celery_app import celery_app

logger = logging.getLogger(__name__)

_METADATA_SYSTEM_PROMPT = (
    "당신은 문서에서 핵심 키워드와 개체명(전문용어, 기관명, 인명, 제품명 등)을 추출하는 "
    "어시스턴트입니다. 문서 내용을 읽고, 이 문서를 대표하는 키워드를 한 줄에 하나씩만 "
    "나열하세요. 번호, 설명, 부가 문장 없이 키워드만 작성하세요. 최대 10개까지만 "
    "작성하세요. 문서에 없는 내용을 추측해서 덧붙이지 마세요. "
    "반드시 한국어(한글)로만 작성하세요. 중국어(한자)나 영어 문장으로 작성하는 것은 금지됩니다. "
    "You must respond only in Korean (Hangul). Never respond in Chinese."
)

# Same local-model context budget rationale as generate_summary — see
# app/pipeline/tasks/summary.py for details.
_MAX_METADATA_INPUT_CHARS = 12_000
_METADATA_MODEL_KEY = "qwen2.5-3b"
_MAX_SUGGESTED_TAGS = 10
_MAX_TAG_LENGTH = 100

# Same drift guard as generate_summary: Qwen sometimes answers in Chinese
# despite the Korean instruction. Applied per-line since keyword lines are
# short and a single stray Han-heavy line shouldn't be treated as a
# whole-response retry trigger the way a summary paragraph is.
_MAX_HAN_RATIO = 0.2


def _han_ratio(text: str) -> float:
    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    return len(re.findall(r"[一-鿿]", stripped)) / len(stripped)


def _parse_keywords(raw: str, exclude: set[str]) -> list[str]:
    """Splits the model's line-per-keyword output into a deduped tag list,
    dropping numbering/bullet prefixes, Han-heavy lines, anything already in
    the document's manual tags, and anything over length."""
    candidates: list[str] = []
    for line in raw.splitlines():
        cleaned = re.sub(r"^[\s\-*\d.)]+", "", line).strip().strip("\"'")
        if not cleaned or len(cleaned) > _MAX_TAG_LENGTH:
            continue
        if _han_ratio(cleaned) > _MAX_HAN_RATIO:
            continue
        candidates.append(cleaned)

    seen: set[str] = set()
    result: list[str] = []
    for tag in candidates:
        key = tag.lower()
        if key in seen or key in exclude:
            continue
        seen.add(key)
        result.append(tag)
        if len(result) >= _MAX_SUGGESTED_TAGS:
            break
    return result


@celery_app.task(name="tasks.extract_metadata", queue="low")
def extract_metadata(document_id: str) -> dict:
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
            doc.suggested_tags = None
            doc.metadata_status = "FAILED"
            db.commit()
            return {"document_id": document_id, "status": "FAILED", "reason": "empty text"}

        doc.metadata_status = "GENERATING"
        db.commit()

        truncated = text[:_MAX_METADATA_INPUT_CHARS]
        provider = get_llm_provider(_METADATA_MODEL_KEY)
        raw = provider.generate(
            _METADATA_SYSTEM_PROMPT,
            [{"role": "user", "content": f"다음 문서에서 핵심 키워드를 추출하세요:\n\n{truncated}"}],
        )

        existing_tags = {t.lower() for t in (doc.tags or [])}
        suggested = _parse_keywords(raw, exclude=existing_tags)

        doc.suggested_tags = suggested or None
        doc.metadata_status = "DONE"
        db.commit()
        return {"document_id": document_id, "status": "DONE", "suggested_tags": suggested}

    except Exception as exc:
        logger.exception("extract_metadata failed", extra={"document_id": document_id})
        db.rollback()
        try:
            doc = db.get(Document, document_id)
            if doc:
                doc.metadata_status = "FAILED"
                db.commit()
        except Exception:
            logger.exception(
                "extract_metadata: failed to record failure state",
                extra={"document_id": document_id},
            )
        return {"document_id": document_id, "status": "FAILED", "error": str(exc)}
    finally:
        db.close()
