"""Content-processing block types: 입력/전처리/분류/개체추출/키워드추출/요약/검증.

입력 loads the run's document text from the DB; the LLM-backed blocks
(분류/개체추출/키워드추출/요약) reuse the same local provider and Korean-drift
guard as the fixed pipeline tasks (tasks/summary.py, tasks/metadata.py).
Every block passes `text` through its output so downstream blocks keep
working regardless of what else a block adds.
"""
import re

from app.pipeline.blocks.base import BaseBlock, BlockContext, BlockResult

# Same local-model budget rationale as tasks/summary.py.
_MAX_LLM_INPUT_CHARS = 12_000
_LLM_MODEL_KEY = "qwen2.5-3b"
_MAX_HAN_RATIO = 0.2

_DEFAULT_CATEGORIES = ["보고서", "계약서", "공문", "매뉴얼", "기타"]


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


class InputBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "input"

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
            text = (doc.parsed_text or "").strip()
            if not text:
                raise ValueError("문서에 추출된 텍스트가 없습니다. 파싱이 완료된 문서인지 확인하세요.")
            return BlockResult(output={
                "document_id": str(doc.id),
                "filename": doc.original_filename,
                "text": text,
            })
        finally:
            db.close()


class PreprocessBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "preprocess"

    def run(self, context: BlockContext) -> BlockResult:
        text = _upstream_text(context)
        # Normalize whitespace: strip control chars, collapse runs of blank
        # lines to one, collapse intra-line whitespace runs to single spaces.
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        cleaned = "\n".join(
            re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()
        )
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return BlockResult(output={
            "text": cleaned,
            "original_length": len(text),
            "cleaned_length": len(cleaned),
        })


class ClassifyBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "classify"

    def run(self, context: BlockContext) -> BlockResult:
        text = _upstream_text(context)
        categories = context.config.get("categories") or _DEFAULT_CATEGORIES
        raw = _generate(
            "당신은 문서를 분류하는 어시스턴트입니다. 주어진 카테고리 중 문서에 가장 잘 맞는 "
            "하나만 골라 그 카테고리 이름만 답하세요. 설명이나 다른 문장은 쓰지 마세요.",
            f"카테고리: {', '.join(categories)}\n\n문서:\n{text[:_MAX_LLM_INPUT_CHARS]}",
        ).strip()
        # The model may echo punctuation or a sentence — take the first
        # category that appears in its answer, else the last (기타-style) one.
        category = next((c for c in categories if c in raw), categories[-1])
        return BlockResult(output={"category": category, "text": text})


class ExtractEntitiesBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "extract_entities"

    def run(self, context: BlockContext) -> BlockResult:
        text = _upstream_text(context)
        raw = _generate(
            "당신은 문서에서 개체명(인명, 기관명, 지명, 제품명, 날짜)을 추출하는 어시스턴트입니다. "
            "문서에 실제로 등장하는 개체명만 한 줄에 하나씩 나열하세요. 번호, 설명 없이 개체명만 "
            "작성하세요. 최대 15개. 반드시 한국어로 작성하세요.",
            f"다음 문서에서 개체명을 추출하세요:\n\n{text[:_MAX_LLM_INPUT_CHARS]}",
        )
        return BlockResult(output={"entities": _parse_lines(raw, 15), "text": text})


class ExtractKeywordsBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "extract_keywords"

    def run(self, context: BlockContext) -> BlockResult:
        text = _upstream_text(context)
        raw = _generate(
            "당신은 문서에서 핵심 키워드를 추출하는 어시스턴트입니다. 이 문서를 대표하는 "
            "키워드를 한 줄에 하나씩만 나열하세요. 번호, 설명 없이 키워드만 작성하세요. "
            "최대 10개. 반드시 한국어(한글)로만 작성하세요.",
            f"다음 문서에서 핵심 키워드를 추출하세요:\n\n{text[:_MAX_LLM_INPUT_CHARS]}",
        )
        return BlockResult(output={"keywords": _parse_lines(raw, 10), "text": text})


class SummarizeBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "summarize"

    def run(self, context: BlockContext) -> BlockResult:
        text = _upstream_text(context)
        system = (
            "당신은 문서를 간결하게 요약하는 어시스턴트입니다. 핵심 주제와 주요 내용을 "
            "요약하세요. 문서에 없는 내용을 추측해서 덧붙이지 마세요. 반드시 한국어(한글)로만 "
            "작성하세요. 중국어(한자)나 영어 문장으로 작성하는 것은 금지됩니다."
        )
        summary = _generate(system, f"다음 문서를 한국어로 요약하세요:\n\n{text[:_MAX_LLM_INPUT_CHARS]}")
        if _han_ratio(summary) > 0.05:
            summary = _generate(
                system,
                f"다음 문서를 요약하세요. 반드시 한국어(한글)로만 작성하세요. 중국어(한자) 사용 금지.\n\n"
                f"{text[:_MAX_LLM_INPUT_CHARS]}",
            )
        return BlockResult(output={"summary": summary.strip(), "text": text})


class ValidateBlock(BaseBlock):
    @property
    def block_type(self) -> str:
        return "validate"

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
