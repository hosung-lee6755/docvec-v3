"""content_blocks: 입력/전처리/분류/개체/키워드/요약/검증 블록 단위 테스트 (LLM·DB 경계는 모킹)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.blocks import content_blocks as cb
from app.pipeline.blocks.base import BlockContext


def _ctx(text="본문 텍스트입니다", config=None, extra=None, document_id="doc-1"):
    upstream = {"text": text, **(extra or {})}
    return BlockContext(
        run_id="r1", block_instance_id="b1", upstream_outputs={"up": upstream},
        config=config or {}, document_id=document_id,
    )


def _fake_llm(monkeypatch, *answers):
    calls = []
    queue = list(answers)

    def _gen(system_prompt, user_content):
        calls.append((system_prompt, user_content))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(cb, "_generate", _gen)
    return calls


# ---- helpers ----
def test_han_ratio_zero_for_empty_and_korean():
    assert cb._han_ratio("") == 0.0
    assert cb._han_ratio("  \n ") == 0.0
    assert cb._han_ratio("한글만 있는 문장") == 0.0


def test_han_ratio_counts_hanja():
    assert cb._han_ratio("漢字") == 1.0
    assert cb._han_ratio("漢a") == 0.5


def test_upstream_text_raises_when_missing():
    ctx = BlockContext(run_id="r", block_instance_id="b", upstream_outputs={"u": {"text": ""}})
    with pytest.raises(ValueError):
        cb._upstream_text(ctx)


def test_upstream_text_skips_empty_outputs():
    ctx = BlockContext(
        run_id="r", block_instance_id="b",
        upstream_outputs={"a": {"foo": 1}, "b": {"text": "ok"}},
    )
    assert cb._upstream_text(ctx) == "ok"


def test_carry_returns_copy_of_first_upstream():
    ctx = _ctx(extra={"k": 1})
    carried = cb._carry(ctx)
    carried["k"] = 2
    assert ctx.upstream_outputs["up"]["k"] == 1
    assert cb._carry(BlockContext(run_id="r", block_instance_id="b")) == {}


def test_parse_lines_cleans_dedupes_and_limits():
    raw = "1. 사과\n- 사과\n* '배'\n\n漢字漢字\n" + "가" * 101 + "\n3) 포도\n딸기"
    assert cb._parse_lines(raw, 3) == ["사과", "배", "포도"]


def test_parse_lines_dedupe_is_case_insensitive():
    assert cb._parse_lines("Python\npython\nPYTHON", 10) == ["Python"]


def test_generate_uses_provider(monkeypatch):
    provider = MagicMock()
    provider.generate.return_value = "답"
    with patch("app.services.llm.get_llm_provider", return_value=provider) as getter:
        assert cb._generate("sys", "usr") == "답"
    getter.assert_called_once_with(cb._LLM_MODEL_KEY)
    provider.generate.assert_called_once_with("sys", [{"role": "user", "content": "usr"}])


# ---- InputBlock ----
def _db_with_doc(doc):
    db = MagicMock()
    db.get.return_value = doc
    return db


def test_input_block_requires_document_id():
    with pytest.raises(ValueError):
        cb.InputBlock().run(BlockContext(run_id="r", block_instance_id="b"))


def test_input_block_returns_stripped_text():
    doc = SimpleNamespace(id="d1", original_filename="a.pdf", parsed_text="  내용  ")
    db = _db_with_doc(doc)
    with patch("app.db.session.get_sync_db", return_value=db):
        result = cb.InputBlock().run(BlockContext(run_id="r", block_instance_id="b", document_id="d1"))
    assert result.output == {"document_id": "d1", "filename": "a.pdf", "text": "내용", "text_source": "original"}
    db.close.assert_called_once()


def _db_with_revision(doc, source, text):
    db = _db_with_doc(doc)
    latest = SimpleNamespace(source=source, parsed_text=text) if source else None
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = latest
    return db


def test_input_block_reads_the_normalized_text_of_the_latest_preprocessing():
    """사전 치환, 정제 규칙, 개인정보 마스킹이 반영된 텍스트로 분석해야 결과에도 반영된다."""
    doc = SimpleNamespace(id="d1", original_filename="a.pdf", parsed_text="ICT 원문 010-1234-5678")
    db = _db_with_revision(doc, "NORMALIZED", " 정보통신기술 원문 *** ")
    with patch("app.db.session.get_sync_db", return_value=db):
        result = cb.InputBlock().run(BlockContext(run_id="r", block_instance_id="b", document_id="d1"))
    assert result.output["text"] == "정보통신기술 원문 ***"
    assert result.output["text_source"] == "normalized"


@pytest.mark.parametrize("source", ["RAG_EDIT", "REVIEW_EDIT", "RESTORE", None])
def test_input_block_uses_parsed_text_when_it_changed_after_preprocessing(source):
    """전처리 뒤 사람이 고친 텍스트가 있거나 스냅샷이 없으면(이전에 처리한 문서) 문서 본문을 쓴다."""
    doc = SimpleNamespace(id="d1", original_filename="a.pdf", parsed_text="고친 본문")
    db = _db_with_revision(doc, source, "고친 본문")
    with patch("app.db.session.get_sync_db", return_value=db):
        result = cb.InputBlock().run(BlockContext(run_id="r", block_instance_id="b", document_id="d1"))
    assert result.output["text"] == "고친 본문"
    assert result.output["text_source"] == "original"


def test_input_block_missing_document():
    db = _db_with_doc(None)
    with patch("app.db.session.get_sync_db", return_value=db):
        with pytest.raises(ValueError, match="찾을 수 없"):
            cb.InputBlock().run(BlockContext(run_id="r", block_instance_id="b", document_id="d1"))
    db.close.assert_called_once()


@pytest.mark.parametrize("parsed", [None, "", "   "])
def test_input_block_empty_text(parsed):
    doc = SimpleNamespace(id="d1", original_filename="a.pdf", parsed_text=parsed)
    with patch("app.db.session.get_sync_db", return_value=_db_with_doc(doc)):
        with pytest.raises(ValueError, match="텍스트가 없"):
            cb.InputBlock().run(BlockContext(run_id="r", block_instance_id="b", document_id="d1"))


# ---- PreprocessBlock ----
def test_preprocess_defaults_strip_control_and_collapse():
    result = cb.PreprocessBlock().run(_ctx("a\x00b   c\t\td\n\n\n\n\ne  "))
    assert result.output["text"] == "ab c d\n\ne"
    assert result.output["original_length"] == len("a\x00b   c\t\td\n\n\n\n\ne  ")
    assert result.output["cleaned_length"] == len(result.output["text"])


def test_preprocess_removes_urls_and_emails():
    text = "참고 https://example.com/x 와 www.foo.kr 메일 a@b.co 끝"
    result = cb.PreprocessBlock().run(_ctx(text, {"remove_urls": True, "remove_emails": True}))
    assert "http" not in result.output["text"]
    assert "www" not in result.output["text"]
    assert "@" not in result.output["text"]
    assert result.output["text"].startswith("참고")


def test_preprocess_removes_special_chars_keeps_korean_punctuation():
    result = cb.PreprocessBlock().run(_ctx("안녕★하세요! #태그 (괄호) 50%", {"remove_special_chars": True}))
    assert result.output["text"] == "안녕하세요! 태그 (괄호) 50%"


def test_preprocess_without_collapse_keeps_spacing():
    result = cb.PreprocessBlock().run(_ctx("a   b", {"collapse_whitespace": False}))
    assert result.output["text"] == "a   b"


def test_preprocess_carries_other_upstream_keys():
    result = cb.PreprocessBlock().run(_ctx("텍스트", extra={"category": "보고서"}))
    assert result.output["category"] == "보고서"


# ---- ClassifyBlock ----
def test_classify_picks_category_found_in_answer(monkeypatch):
    calls = _fake_llm(monkeypatch, " 이 문서는 '계약서' 입니다. ")
    result = cb.ClassifyBlock().run(_ctx())
    assert result.output["category"] == "계약서"
    assert ", ".join(cb._DEFAULT_CATEGORIES) in calls[0][1]


def test_classify_falls_back_to_last_category(monkeypatch):
    _fake_llm(monkeypatch, "모르겠음")
    assert cb.ClassifyBlock().run(_ctx()).output["category"] == "기타"


def test_classify_uses_custom_categories(monkeypatch):
    _fake_llm(monkeypatch, "B")
    result = cb.ClassifyBlock().run(_ctx(config={"categories": ["A", "B", "C"]}))
    assert result.output["category"] == "B"


def test_classify_prompt_explains_default_categories_and_includes_filename(monkeypatch):
    calls = _fake_llm(monkeypatch, "소개서")
    cb.ClassifyBlock().run(_ctx(extra={"filename": "AI_Servor_자료.pdf"}))
    system_prompt, user_content = calls[0]
    assert "- 소개서:" in system_prompt and "주제로 고르지 마세요" in system_prompt
    assert "파일명: AI_Servor_자료.pdf" in user_content


def test_classify_custom_categories_get_no_hints(monkeypatch):
    calls = _fake_llm(monkeypatch, "B")
    cb.ClassifyBlock().run(_ctx(config={"categories": ["A", "B"]}))
    assert "카테고리 설명" not in calls[0][0]


def test_classify_truncates_input(monkeypatch):
    calls = _fake_llm(monkeypatch, "기타")
    cb.ClassifyBlock().run(_ctx("가" * (cb._MAX_LLM_INPUT_CHARS + 500)))
    document_part = calls[0][1].split("문서:\n", 1)[1]  # 카테고리 이름에 든 글자는 세지 않는다
    assert document_part.count("가") == cb._MAX_LLM_INPUT_CHARS


# ---- Entities / Keywords ----
def test_extract_entities_parses_and_caps(monkeypatch):
    calls = _fake_llm(monkeypatch, "1. 홍길동\n2. 삼성전자\n3. 서울")
    result = cb.ExtractEntitiesBlock().run(_ctx(config={"max_entities": 2}))
    assert result.output["entities"] == ["홍길동", "삼성전자"]
    assert "최대 2개" in calls[0][0]


def test_extract_entities_clamps_max_and_custom_types(monkeypatch):
    calls = _fake_llm(monkeypatch, "홍길동")
    cb.ExtractEntitiesBlock().run(_ctx(config={"max_entities": 999, "entity_types": ["인명"]}))
    assert "최대 30개" in calls[0][0]
    assert "(인명)" in calls[0][0]
    cb.ExtractEntitiesBlock().run(_ctx(config={"max_entities": -5}))
    assert "최대 1개" in calls[1][0]


def test_extract_keywords_parses(monkeypatch):
    _fake_llm(monkeypatch, "- 에너지\n- 탄소\n- 에너지")
    result = cb.ExtractKeywordsBlock().run(_ctx())
    assert result.output["keywords"] == ["에너지", "탄소"]
    assert result.output["text"] == "본문 텍스트입니다"


def test_extract_keywords_clamps_limit(monkeypatch):
    calls = _fake_llm(monkeypatch, "키워드")
    cb.ExtractKeywordsBlock().run(_ctx(config={"max_keywords": 100}))
    assert "최대 30개" in calls[0][0]


# ---- Summarize ----
def test_summarize_paragraph_default(monkeypatch):
    calls = _fake_llm(monkeypatch, "  요약문입니다  ")
    result = cb.SummarizeBlock().run(_ctx())
    assert result.output["summary"] == "요약문입니다"
    assert "문단" in calls[0][0]
    assert len(calls) == 1


def test_summarize_bullets_and_custom_prompt(monkeypatch):
    calls = _fake_llm(monkeypatch, "- 항목")
    cb.SummarizeBlock().run(_ctx(config={"format": "bullets", "prompt": "  핵심만  "}))
    assert "글머리표" in calls[0][0]
    assert calls[0][1].startswith("핵심만\n\n")


def test_summarize_retries_when_han_drift(monkeypatch):
    calls = _fake_llm(monkeypatch, "这是中文摘要内容很多漢字", "한국어 요약")
    result = cb.SummarizeBlock().run(_ctx())
    assert len(calls) == 2
    assert result.output["summary"] == "한국어 요약"
    assert "중국어(한자) 사용 금지" in calls[1][1]


# ---- Validate ----
def test_validate_passes_for_good_output():
    ctx = _ctx("충분히 긴 텍스트입니다", extra={"summary": "s", "keywords": ["k"], "entities": ["e"]})
    result = cb.ValidateBlock().run(ctx)
    assert result.output["is_valid"] is True
    assert result.output["problems"] == []


def test_validate_reports_every_problem():
    ctx = _ctx("짧", extra={"summary": "  ", "keywords": [], "entities": []})
    result = cb.ValidateBlock().run(ctx)
    assert result.output["is_valid"] is False
    assert len(result.output["problems"]) == 4


def test_validate_respects_min_length_config():
    ctx = _ctx("12345", config={"min_text_length": 3})
    assert cb.ValidateBlock().run(ctx).output["is_valid"] is True


def test_validate_handles_no_upstream():
    ctx = BlockContext(run_id="r", block_instance_id="b")
    result = cb.ValidateBlock().run(ctx)
    assert result.output["is_valid"] is False


# ---- metadata ----
@pytest.mark.parametrize("block,btype,schema", [
    (cb.InputBlock, "input", None),
    (cb.PreprocessBlock, "preprocess", cb.PreprocessConfig),
    (cb.ClassifyBlock, "classify", cb.ClassifyConfig),
    (cb.ExtractEntitiesBlock, "extract_entities", cb.ExtractEntitiesConfig),
    (cb.ExtractKeywordsBlock, "extract_keywords", cb.ExtractKeywordsConfig),
    (cb.SummarizeBlock, "summarize", cb.SummarizeConfig),
    (cb.ValidateBlock, "validate", cb.ValidateConfig),
])
def test_block_metadata(block, btype, schema):
    instance = block()
    assert instance.block_type == btype
    assert instance.config_schema is schema
    assert instance.category


def test_config_schemas_reject_bad_types():
    with pytest.raises(Exception):
        cb.ExtractKeywordsConfig(max_keywords="abc")
    assert cb.SummarizeConfig().format == "paragraph"


def test_default_categories_distinguish_common_korean_business_documents():
    from app.pipeline.blocks.content_blocks import _DEFAULT_CATEGORIES

    # 공고문·제안서·소개서·가이드라인이 전부 "보고서"로 뭉개지지 않도록 세분화돼 있어야 한다.
    for name in ("공고문", "제안서", "소개서", "가이드라인", "기준서", "사례집", "진단보고서", "보고서", "계약서", "공문", "매뉴얼"):
        assert name in _DEFAULT_CATEGORIES
    assert _DEFAULT_CATEGORIES[-1] == "기타"  # 모델 답이 어디에도 안 맞을 때의 폴백
