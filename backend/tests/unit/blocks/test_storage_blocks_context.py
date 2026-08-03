from types import SimpleNamespace

from app.pipeline.blocks.storage_blocks import _llm_chunk_contexts, _structural_context


def test_structural_context_joins_title_and_section_path():
    result = _structural_context("에너지 진단 보고서", ["2장 결과", "2.1 온실가스 배출량"])

    assert result == "에너지 진단 보고서 > 2장 결과 > 2.1 온실가스 배출량"


def test_structural_context_empty_when_no_title_or_section_path():
    assert _structural_context(None, None) == ""


def test_structural_context_falls_back_to_title_only():
    assert _structural_context("보고서 제목", None) == "보고서 제목"


def test_structural_context_falls_back_to_section_path_only():
    assert _structural_context(None, ["1장", "1.1절"]) == "1장 > 1.1절"


def _fake_chunk(chunk_id: str, text: str):
    return SimpleNamespace(id=chunk_id, chunk_text=text)


def test_llm_chunk_contexts_strips_stray_tool_call_tag(monkeypatch):
    import app.pipeline.blocks.storage_blocks as storage_blocks

    monkeypatch.setattr(
        "app.pipeline.blocks.content_blocks._generate",
        lambda system_prompt, user_content: "데이터 파이프라인 구축 계획을 설명한다.<tool_call>",
    )
    chunks = [_fake_chunk("c1", "본문 텍스트")]

    result = storage_blocks._llm_chunk_contexts("제목", "발췌", chunks)

    assert result["c1"] == "데이터 파이프라인 구축 계획을 설명한다."


def test_llm_chunk_contexts_skips_chunk_when_generate_raises(monkeypatch):
    import app.pipeline.blocks.storage_blocks as storage_blocks

    def _boom(system_prompt, user_content):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("app.pipeline.blocks.content_blocks._generate", _boom)
    chunks = [_fake_chunk("c1", "본문 텍스트")]

    result = storage_blocks._llm_chunk_contexts("제목", "발췌", chunks)

    assert result == {}


def test_llm_chunk_contexts_respects_max_chunks_cap(monkeypatch):
    import app.pipeline.blocks.storage_blocks as storage_blocks

    calls = []

    def _record(system_prompt, user_content):
        calls.append(user_content)
        return "요약 문장"

    monkeypatch.setattr("app.pipeline.blocks.content_blocks._generate", _record)
    monkeypatch.setattr(storage_blocks, "_CONTEXT_LLM_MAX_CHUNKS", 2)
    chunks = [_fake_chunk(f"c{i}", f"청크 {i}") for i in range(5)]

    result = storage_blocks._llm_chunk_contexts("제목", "발췌", chunks)

    assert len(calls) == 2
    assert set(result.keys()) == {"c0", "c1"}
