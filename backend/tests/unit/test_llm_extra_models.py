"""설정으로 더하는 답변 모델(전체 점검 2-3)."""
import json

import pytest

from app.api.v1.endpoints.chat import _is_model_available
from app.services import llm
from app.services.external_model_policy import is_external_backend

BUILTIN = {"qwen2.5-3b": {"repo_id": "qwen2.5:3b", "backend": "local", "label": "Qwen"}}
LOCAL = {"key": "exaone-7.8b", "repo_id": "exaone3.5:7.8b", "backend": "local", "label": "EXAONE (로컬)"}
SERVER = {
    "key": "qwen-14b", "repo_id": "Qwen/Qwen2.5-14B-Instruct", "backend": "openai_compatible",
    "label": "Qwen 14B (사내)", "base_url": "http://gpu-server:8000/v1",
}


def test_adds_local_and_compatible_models():
    models = llm.parse_extra_models(json.dumps([LOCAL, SERVER]), BUILTIN)

    assert models["exaone-7.8b"] == {"repo_id": "exaone3.5:7.8b", "backend": "local", "label": "EXAONE (로컬)"}
    assert models["qwen-14b"]["base_url"] == "http://gpu-server:8000/v1"


@pytest.mark.parametrize("raw", ["", "   ", None, "not json", '{"key": "x"}'])
def test_empty_or_broken_setting_adds_nothing(raw):
    assert llm.parse_extra_models(raw, BUILTIN) == {}


@pytest.mark.parametrize("bad", [
    {**LOCAL, "key": "qwen2.5-3b"},
    {**LOCAL, "backend": "openai"},
    {**LOCAL, "label": ""},
    {**SERVER, "base_url": "gpu-server:8000"},
    {key: value for key, value in SERVER.items() if key != "base_url"},
    "text",
])
def test_bad_entry_is_skipped_and_good_ones_survive(bad):
    models = llm.parse_extra_models(json.dumps([bad, LOCAL]), BUILTIN)

    assert list(models) == ["exaone-7.8b"]


def test_duplicate_key_inside_the_setting_keeps_the_first():
    models = llm.parse_extra_models(json.dumps([LOCAL, {**LOCAL, "label": "둘째"}]), BUILTIN)

    assert models["exaone-7.8b"]["label"] == "EXAONE (로컬)"


def test_compatible_model_uses_the_configured_server(monkeypatch):
    created = {}

    class FakeProvider:
        def __init__(self, model, api_key, base_url=None):
            created.update(model=model, api_key=api_key, base_url=base_url)

    monkeypatch.setattr(llm, "OpenAILLMProvider", FakeProvider)
    monkeypatch.setitem(llm.LLM_MODEL_REGISTRY, "qwen-14b", {k: v for k, v in SERVER.items() if k != "key"})
    monkeypatch.setattr(llm, "_local_provider_cache", {})
    monkeypatch.setattr(llm.settings, "llm_compatible_api_key", None)

    first = llm.get_llm_provider("qwen-14b")

    assert created == {
        "model": "Qwen/Qwen2.5-14B-Instruct", "api_key": "not-needed", "base_url": "http://gpu-server:8000/v1",
    }
    assert llm.get_llm_provider("qwen-14b") is first


def test_compatible_server_is_in_house_and_always_selectable():
    assert not is_external_backend("openai_compatible")
    assert _is_model_available({"backend": "openai_compatible", "repo_id": "m"}, set(), set())
    assert not _is_model_available({"backend": "local", "repo_id": "m"}, set(), set())
    assert _is_model_available({"backend": "openai", "repo_id": "m"}, set(), {"openai"})
