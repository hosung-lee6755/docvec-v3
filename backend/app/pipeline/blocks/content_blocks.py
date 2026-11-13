"""Content-processing block types: 입력/전처리/분류/개체추출/키워드추출/요약/검증.

입력 loads the run's document text from the DB; the LLM-backed blocks
(분류/개체추출/키워드추출/요약) reuse the same local provider and Korean-drift
guard as the fixed pipeline tasks (tasks/summary.py, tasks/metadata.py).
Every block passes `text` through its output so downstream blocks keep
working regardless of what else a block adds.
"""
import re
from typing import Literal

from pydantic import BaseModel

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult

# Same local-model budget rationale as tasks/summary.py.
_MAX_LLM_INPUT_CHARS = 12_000
_LLM_MODEL_KEY = "qwen2.5-3b"
_MAX_HAN_RATIO = 0.2

# 설정에 categories 가 없을 때의 기본 분류 — 공고문·제안서·소개서 등이 전부 "보고서"로 뭉개지던 문제를
# 막기 위해 세분화했다. 모델 답이 어디에도 안 맞으면 마지막 항목("기타")으로 폴백한다.
_DEFAULT_CATEGORIES = [
    "공고문", "제안서", "진단보고서", "가이드라인", "매뉴얼", "사례집", "소개서", "기준서",
    "계약서", "공문", "보고서", "기타",
]


class PreprocessConfig(BaseModel):
    remove_urls: bool = False
    remove_emails: bool = False
    remove_special_chars: bool = False
    collapse_whitespace: bool = True


class ClassifyConfig(BaseModel):
    categories: list[str] | None = None


class ExtractEntitiesConfig(BaseModel):
    max_entities: int = 15
    entity_types: list[str] | None = None


class ExtractKeywordsConfig(BaseModel):
    max_keywords: int = 10


class SummarizeConfig(BaseModel):
    # 에디터 선택지와 같은 두 값만 받는다. 다른 문자열은 예전엔 조용히 문단형으로 처리됐다.
    format: Literal["paragraph", "bullets"] = "paragraph"
    prompt: str | None = None


class ValidateConfig(BaseModel):
    min_text_length: int = 10


def _han_ratio(text: str) -> float:
    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    return len(re.findall(r"[一-鿿]", stripped)) / len(stripped)


def _generate(system_prompt: str, user_content: str) -> str:
    from app.services.llm import get_llm_provider

    provider = get_llm_provider(_LLM_MODEL_KEY)
    return provider.generate(system_prompt, [{"role": "user", "content": user_content}])


def _upstream_text(context: BlockContext) -> str:
    """The text handed down from the closest upstream block that produced one."""
    for output in context.upstream_outputs.values():
        text = output.get("text")
        if text:
            return text
    raise ValueError("상위 블록에서 전달된 텍스트가 없습니다. 입력 블록부터 연결됐는지 확인하세요.")


def _carry(context: BlockContext) -> dict:
    """Accumulated result carried down a linear chain: each block passes its
    upstream's whole output through and adds its own keys, so e.g.
    요약 -> 키워드 추출 ends with BOTH summary and keywords."""
    return dict(next(iter(context.upstream_outputs.values()), {}))


# 기본 분류 목록의 이름만으로는 모델이 주제로 오분류한다("버스 분석" 요약본 → 공고문) — 종류 판단 기준을 함께 준다.
_CATEGORY_HINTS = {
    "공고문": "지원사업·모집·입찰 등을 알리는 공식 공고(신청 자격·기간·접수 방법이 있다)",
    "제안서": "사업 수행을 제안하는 문서(제안 배경·수행 방안·추진 일정)",
    "진단보고서": "현장·설비·에너지 등을 진단한 결과 보고서",
    "가이드라인": "따라야 할 원칙과 기준을 제시하는 지침",
    "매뉴얼": "사용·운영 절차를 단계별로 설명하는 안내서",
    "사례집": "여러 사례를 모아 소개하는 자료",
    "소개서": "제품·서비스·기관을 소개하는 자료",
    "기준서": "검수·평가 등의 기준과 항목을 정의한 문서",
    "계약서": "당사자 간 권리·의무를 정한 계약 문서",
    "공문": "기관 간 주고받는 공식 시행·회신 문서",
    "보고서": "조사·분석·연구 결과를 정리한 보고서",
    "기타": "위 어디에도 맞지 않을 때",
}

_ANSWER_NOISE =" \t\r\n'\"`.,。·「」『』()[]"


def _pick_category(raw: str, categories: list[str]) -> str:
    """Resolve the model's answer to one of `categories`.

    The prompt asks for the bare category name, but the model sometimes answers
    with a sentence or lists several candidates. An answer that IS a candidate
    wins; otherwise the candidate mentioned first wins (a longer one on a tie,
    so "진단보고서" beats "보고서"), never the one that merely sits first in the
    configured list. No match falls back to the last category (기타-style)."""
    answer = raw.strip(_ANSWER_NOISE)
    if answer in categories:
        return answer
    mentioned = [(raw.find(c), -len(c), c) for c in categories if c in raw]
    if mentioned:
        return min(mentioned)[2]
    return categories[-1]


def _parse_lines(raw: str, max_items: int) -> list[str]:
    """Line-per-item LLM output -> cleaned, deduped list (same approach as
    tasks/metadata.py's keyword parsing)."""
    items: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        cleaned = re.sub(r"^[\s\-*\d.)]+", "", line).strip().strip("\"'")
        if not cleaned or len(cleaned) > 100 or _han_ratio(cleaned) > _MAX_HAN_RATIO:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(cleaned)
        if len(items) >= max_items:
            break
    return items


def _analysis_text(db, doc) -> tuple[str, str]:
    """분석할 텍스트와 그 출처("normalized" | "original").

    가장 최근 스냅샷이 청크 분할이 남긴 최종 텍스트(NORMALIZED)면 그것을 쓴다. 정제 규칙, 사전 치환,
    개인정보 마스킹이 반영돼 있어 분석 결과도 검색 청크와 같은 텍스트를 본다. 그 뒤에 사람이 본문을
    고쳤거나(REVIEW_EDIT, RAG_EDIT, RESTORE) 이 기능 전에 처리돼 스냅샷이 없으면 문서 본문을 쓴다."""
    from app.db.models.document_revision import NORMALIZED_REVISION_SOURCE, DocumentTextRevision

    latest = (
        db.query(DocumentTextRevision)
        .filter(DocumentTextRevision.document_id == doc.id)
        .order_by(DocumentTextRevision.created_at.desc())
        .first()
    )
    if latest is not None and latest.source == NORMALIZED_REVISION_SOURCE:
        normalized = (latest.parsed_text or "").strip()
        if normalized:
            return normalized, "normalized"
    return (doc.parsed_text or "").strip(), "original"


class InputBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "input"

    @property
    def category(self) -> str:
        # Absorbed into the new 텍스트 추출 block in Phase 3 — kept as-is,
        # unmodified behavior, until that block replaces it.
        return "레거시"

    def run(self, context: BlockContext) -> BlockResult:
        from app.db.models.document import Document
        from app.db.session import get_sync_db

        if not context.document_id:
            raise ValueError("실행할 문서가 지정되지 않았습니다. 실행 시 문서를 선택하세요.")

        db = get_sync_db()
        try:
            doc = db.get(Document, context.document_id)
            if doc is None:
                raise ValueError("지정된 문서를 찾을 수 없습니다.")
            text, text_source = _analysis_text(db, doc)
            if not text:
                raise ValueError("문서에 추출된 텍스트가 없습니다. 파싱이 완료된 문서인지 확인하세요.")
            return BlockResult(output={
                "document_id": str(doc.id),
                "filename": doc.original_filename,
                "text": text,
                "text_source": text_source,
            })
        finally:
            db.close()


class PreprocessBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "preprocess"

    @property
    def category(self) -> str:
        # Replaced by the new 텍스트 정제 block in Phase 4 — kept as-is,
        # unmodified behavior, until that block replaces it.
        return "레거시"

    @property
    def config_schema(self) -> type[BaseModel] | None:
        return PreprocessConfig

    def run(self, context: BlockContext) -> BlockResult:
        text = _upstream_text(context)
        # Control chars are always stripped; the rest is config-driven.
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        if context.config.get("remove_urls", False):
            cleaned = re.sub(r"https?://\S+|www\.\S+", "", cleaned)
        if context.config.get("remove_emails", False):
            cleaned = re.sub(r"\S+@\S+\.\S+", "", cleaned)
        if context.config.get("remove_special_chars", False):
            # Keep Korean/alphanumeric/space and basic sentence punctuation.
            cleaned = re.sub(r"[^\w\s가-힣.,!?%()·\-]", "", cleaned)
        if context.config.get("collapse_whitespace", True):
            cleaned = "\n".join(
                re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()
            )
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = cleaned.strip()
        return BlockResult(output={
            **_carry(context),
            "text": cleaned,
            "original_length": len(text),
            "cleaned_length": len(cleaned),
        })


class ClassifyBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "classify"

    @property
    def category(self) -> str:
        return "분석"

    @property
    def config_schema(self) -> type[BaseModel] | None:
        return ClassifyConfig

    def run(self, context: BlockContext) -> BlockResult:
        text = _upstream_text(context)
        # UI 설정에 섞인 빈 항목은 `"" in 응답` 이 항상 참이라 선택과 폴백을 망친다.
        categories = [c for c in (context.config.get("categories") or []) if c and c.strip()]
        categories = categories or _DEFAULT_CATEGORIES
        upstream = next(iter(context.upstream_outputs.values()), {})
        filename = str(upstream.get("filename") or "").strip()
        hints = [f"- {name}: {_CATEGORY_HINTS[name]}" for name in categories if name in _CATEGORY_HINTS]
        raw = _generate(
            "당신은 문서를 분류하는 어시스턴트입니다. 주어진 카테고리 중 문서에 가장 잘 맞는 "
            "하나만 골라 그 카테고리 이름만 답하세요. 설명이나 다른 문장은 쓰지 마세요. "
            "문서 종류(형식과 목적)로 고르고, 다루는 주제로 고르지 마세요."
            + ("\n카테고리 설명:\n" + "\n".join(hints) if hints else ""),
            f"카테고리: {', '.join(categories)}\n\n"
            + (f"파일명: {filename}\n" if filename else "")
            + f"문서:\n{text[:_MAX_LLM_INPUT_CHARS]}",
        ).strip()
        category = _pick_category(raw, categories)
        return BlockResult(output={**_carry(context), "category": category, "text": text})


class ExtractEntitiesBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "extract_entities"

    @property
    def category(self) -> str:
        return "분석"

    @property
    def config_schema(self) -> type[BaseModel] | None:
        return ExtractEntitiesConfig

    def run(self, context: BlockContext) -> BlockResult:
        text = _upstream_text(context)
        max_entities = max(1, min(int(context.config.get("max_entities", 15)), 30))
        entity_types = context.config.get("entity_types") or ["인명", "기관명", "지명", "제품명", "날짜"]
        raw = _generate(
            f"당신은 문서에서 개체명({', '.join(entity_types)})을 추출하는 어시스턴트입니다. "
            "문서에 실제로 등장하는 개체명만 한 줄에 하나씩 나열하세요. 번호, 설명 없이 개체명만 "
            f"작성하세요. 최대 {max_entities}개. 반드시 한국어로 작성하세요.",
            f"다음 문서에서 개체명을 추출하세요:\n\n{text[:_MAX_LLM_INPUT_CHARS]}",
        )
        return BlockResult(output={
            **_carry(context), "entities": _parse_lines(raw, max_entities), "text": text,
        })


class ExtractKeywordsBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "extract_keywords"

    @property
    def category(self) -> str:
        return "분석"

    @property
    def config_schema(self) -> type[BaseModel] | None:
        return ExtractKeywordsConfig

    def run(self, context: BlockContext) -> BlockResult:
        text = _upstream_text(context)
        max_keywords = max(1, min(int(context.config.get("max_keywords", 10)), 30))
        raw = _generate(
            "당신은 문서에서 핵심 키워드를 추출하는 어시스턴트입니다. 이 문서를 대표하는 "
            "키워드를 한 줄에 하나씩만 나열하세요. 번호, 설명 없이 키워드만 작성하세요. "
            f"최대 {max_keywords}개. 반드시 한국어(한글)로만 작성하세요.",
            f"다음 문서에서 핵심 키워드를 추출하세요:\n\n{text[:_MAX_LLM_INPUT_CHARS]}",
        )
        return BlockResult(output={
            **_carry(context), "keywords": _parse_lines(raw, max_keywords), "text": text,
        })


class SummarizeBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "summarize"

    @property
    def category(self) -> str:
        return "분석"

    @property
    def config_schema(self) -> type[BaseModel] | None:
        return SummarizeConfig

    def run(self, context: BlockContext) -> BlockResult:
        text = _upstream_text(context)
        style = context.config.get("format", "paragraph")
        custom_prompt = (context.config.get("prompt") or "").strip()

        style_instruction = (
            "글머리표(-) 목록으로 항목별로 요약하세요."
            if style == "bullets"
            else "자연스러운 문단 형태로 요약하세요."
        )
        system = (
            "당신은 문서를 간결하게 요약하는 어시스턴트입니다. 핵심 주제와 주요 내용을 "
            f"요약하세요. {style_instruction} "
            "문서에 없는 내용을 추측해서 덧붙이지 마세요. 반드시 한국어(한글)로만 "
            "작성하세요. 중국어(한자)나 영어 문장으로 작성하는 것은 금지됩니다."
        )
        # User-supplied instruction rides in the user turn so it can steer
        # focus/format without being able to unset the Korean-only guard above.
        user_prefix = f"{custom_prompt}\n\n" if custom_prompt else ""
        summary = _generate(
            system,
            f"{user_prefix}다음 문서를 한국어로 요약하세요:\n\n{text[:_MAX_LLM_INPUT_CHARS]}",
        )
        if _han_ratio(summary) > 0.05:
            summary = _generate(
                system,
                f"{user_prefix}다음 문서를 요약하세요. 반드시 한국어(한글)로만 작성하세요. "
                f"중국어(한자) 사용 금지.\n\n{text[:_MAX_LLM_INPUT_CHARS]}",
            )
        return BlockResult(output={**_carry(context), "summary": summary.strip(), "text": text})


class ValidateBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "validate"

    @property
    def category(self) -> str:
        return "분석"

    @property
    def config_schema(self) -> type[BaseModel] | None:
        return ValidateConfig

    def run(self, context: BlockContext) -> BlockResult:
        upstream = next(iter(context.upstream_outputs.values()), {})
        min_length = int(context.config.get("min_text_length", 10))
        text = upstream.get("text", "")
        problems: list[str] = []
        if len(text.strip()) < min_length:
            problems.append(f"텍스트가 최소 길이({min_length}자)보다 짧습니다")
        if "summary" in upstream and not upstream["summary"].strip():
            problems.append("요약이 비어 있습니다")
        if "keywords" in upstream and not upstream["keywords"]:
            problems.append("키워드가 추출되지 않았습니다")
        if "entities" in upstream and not upstream["entities"]:
            problems.append("개체명이 추출되지 않았습니다")
        return BlockResult(output={
            **upstream,
            "is_valid": not problems,
            "problems": problems,
        })
