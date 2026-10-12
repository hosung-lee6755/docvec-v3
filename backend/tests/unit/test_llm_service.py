"""Coverage for app.services.llm — provider classes, registry lookup and cost
estimation. torch/transformers/openai/anthropic are replaced by fakes injected
into sys.modules so no model is loaded and no network call is made."""

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import llm

# ----------------------------------------------------------- base provider


class _Echo(llm.LLMProvider):
    def generate(self, system_prompt, messages):
        return f"{system_prompt}|{len(messages)}"


def test_base_stream_default_generates_then_emits_once():
    seen = []

    out = _Echo().generate_stream("sys", [{"role": "user", "content": "x"}], seen.append)

    assert out == "sys|1"
    assert seen == ["sys|1"]


def test_base_vision_not_supported():
    with pytest.raises(NotImplementedError, match="_Echo does not support vision"):
        _Echo().generate_vision("s", b"img", "image/png", "p")


# ----------------------------------------------------------- local provider


class _Inputs(dict):
    def to(self, _device):
        return self


def _local_provider(cuda=False):
    torch = MagicMock()
    torch.cuda.is_available.return_value = cuda
    transformers = MagicMock()
    tokenizer = transformers.AutoTokenizer.from_pretrained.return_value
    model = transformers.AutoModelForCausalLM.from_pretrained.return_value.to.return_value
    tokenizer.apply_chat_template.return_value = "PROMPT"
    tokenizer.return_value = _Inputs(input_ids=SimpleNamespace(shape=(1, 3)))
    modules = {"torch": torch, "transformers": transformers}
    with patch.dict("sys.modules", modules):
        provider = llm.LocalLLMProvider("repo/x")
    return provider, torch, transformers, tokenizer, model


def test_local_provider_uses_fp32_on_cpu():
    _p, torch, transformers, _tok, _model = _local_provider(cuda=False)

    kwargs = transformers.AutoModelForCausalLM.from_pretrained.call_args.kwargs
    assert kwargs["torch_dtype"] is torch.float32
    transformers.AutoModelForCausalLM.from_pretrained.return_value.to.assert_called_with("cpu")


def test_local_provider_uses_fp16_on_gpu():
    _p, torch, transformers, _tok, _model = _local_provider(cuda=True)

    kwargs = transformers.AutoModelForCausalLM.from_pretrained.call_args.kwargs
    assert kwargs["torch_dtype"] is torch.float16
    transformers.AutoModelForCausalLM.from_pretrained.return_value.to.assert_called_with("cuda")


def test_local_generate_decodes_only_new_tokens_with_floor_and_penalty():
    provider, _t, _tf, tokenizer, model = _local_provider()
    model.generate.return_value = [[1, 2, 3, 40, 50]]
    tokenizer.decode.return_value = "생성된 답"

    out = provider.generate("sys", [{"role": "user", "content": "hi"}])

    assert out == "생성된 답"
    tokenizer.apply_chat_template.assert_called_once_with(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        tokenize=False, add_generation_prompt=True,
    )
    assert tokenizer.decode.call_args.args[0] == [40, 50]
    gen_kwargs = model.generate.call_args.kwargs
    assert gen_kwargs["min_new_tokens"] == 48
    assert gen_kwargs["max_new_tokens"] == 512
    assert gen_kwargs["do_sample"] is False
    assert gen_kwargs["repetition_penalty"] == pytest.approx(1.15)


def test_local_generate_stream_reports_accumulated_text_and_returns_full_text():
    provider, _t, transformers, _tok, model = _local_provider()
    transformers.TextIteratorStreamer.return_value = ["안녕", "하세요"]
    seen = []
    with patch.dict("sys.modules", {"transformers": transformers}):
        out = provider.generate_stream("sys", [], seen.append)

    assert out == "안녕하세요"
    assert seen == ["안녕", "안녕하세요"]
    model.generate.assert_called_once()
    assert model.generate.call_args.kwargs["streamer"] is transformers.TextIteratorStreamer.return_value


def test_local_generate_stream_ignores_callback_errors():
    provider, _t, transformers, _tok, _model = _local_provider()
    transformers.TextIteratorStreamer.return_value = ["a", "b"]

    def boom(_text):
        raise RuntimeError("redis down")

    with patch.dict("sys.modules", {"transformers": transformers}):
        assert provider.generate_stream("s", [], boom) == "ab"


# ----------------------------------------------------------- openai provider


def _openai_provider():
    openai_mod = MagicMock()
    with patch.dict("sys.modules", {"openai": openai_mod}):
        provider = llm.OpenAILLMProvider("gpt-4o-mini", "sk-test")
    return provider, openai_mod.OpenAI.return_value, openai_mod


def _openai_response(content, usage=(10, 5)):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]) if usage else None,
    )


def test_openai_generate_prepends_system_prompt_and_records_usage():
    provider, client, openai_mod = _openai_provider()
    client.chat.completions.create.return_value = _openai_response("답변", usage=(12, 7))

    out = provider.generate("sys", [{"role": "user", "content": "q"}])

    assert out == "답변"
    openai_mod.OpenAI.assert_called_once_with(api_key="sk-test")
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert provider.last_usage == {"input_tokens": 12, "output_tokens": 7}


def test_openai_generate_handles_missing_usage_and_empty_content():
    provider, client, _ = _openai_provider()
    client.chat.completions.create.return_value = _openai_response(None, usage=None)

    assert provider.generate("s", []) == ""
    assert provider.last_usage is None


def test_openai_vision_sends_base64_data_url():
    provider, client, _ = _openai_provider()
    client.chat.completions.create.return_value = _openai_response("설명")

    out = provider.generate_vision("sys", b"\x89PNG", "image/png", "describe")

    assert out == "설명"
    content = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    expected = "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode()
    assert content[1]["image_url"]["url"] == expected


# --------------------------------------------------------- anthropic provider


def _anthropic_provider():
    anthropic_mod = MagicMock()
    with patch.dict("sys.modules", {"anthropic": anthropic_mod}):
        provider = llm.AnthropicLLMProvider("claude-x", "ak")
    return provider, anthropic_mod.Anthropic.return_value, anthropic_mod


def _anthropic_response(blocks, usage=(3, 4)):
    return SimpleNamespace(
        content=[SimpleNamespace(type=t, text=x) for t, x in blocks],
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]) if usage else None,
    )


def test_anthropic_generate_joins_text_blocks_only_and_records_usage():
    provider, client, anthropic_mod = _anthropic_provider()
    client.messages.create.return_value = _anthropic_response(
        [("text", "하나"), ("tool_use", "IGNORED"), ("text", "둘")]
    )

    out = provider.generate("sys", [{"role": "user", "content": "q"}])

    assert out == "하나둘"
    anthropic_mod.Anthropic.assert_called_once_with(api_key="ak")
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["system"] == "sys" and kwargs["max_tokens"] == 1024
    assert provider.last_usage == {"input_tokens": 3, "output_tokens": 4}


def test_anthropic_generate_without_usage_keeps_last_usage_none():
    provider, client, _ = _anthropic_provider()
    client.messages.create.return_value = _anthropic_response([("text", "x")], usage=None)

    provider.generate("s", [])

    assert provider.last_usage is None


def test_anthropic_vision_builds_image_source_block():
    provider, client, _ = _anthropic_provider()
    client.messages.create.return_value = _anthropic_response([("text", "그림 설명")])

    out = provider.generate_vision("sys", b"jpg", "image/jpeg", "prompt")

    assert out == "그림 설명"
    content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert content[0]["source"] == {
        "type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b"jpg").decode(),
    }
    assert content[1] == {"type": "text", "text": "prompt"}


# -------------------------------------------------------------- registry/cost


@pytest.mark.parametrize(
    "model,inp,out,expected",
    [
        ("gpt-4o-mini", 1_000_000, 1_000_000, 0.75),
        ("gpt-4o", 1000, 500, 0.0075),
        ("claude-3-5-haiku", 0, 0, 0.0),
        ("qwen2.5-3b", 5000, 5000, 0.0),  # local models are free
        ("unknown-model", 1, 1, 0.0),
    ],
)
def test_estimate_cost_usd(model, inp, out, expected):
    assert llm.estimate_cost_usd(model, inp, out) == pytest.approx(expected)


def test_get_llm_provider_unknown_model_raises():
    with pytest.raises(ValueError, match="Unknown LLM model"):
        llm.get_llm_provider("nope")


def test_get_llm_provider_caches_local_model_instances():
    created = []

    class FakeLocal:
        def __init__(self, repo_id):
            created.append(repo_id)

    with patch.dict(llm._local_provider_cache, {}, clear=True), \
         patch.object(llm, "LocalLLMProvider", FakeLocal):
        first = llm.get_llm_provider("qwen2.5-3b")
        second = llm.get_llm_provider("qwen2.5-3b")

    assert first is second
    assert created == ["Qwen/Qwen2.5-3B-Instruct"]


@pytest.mark.parametrize(
    "model,message", [("gpt-4o", "OpenAI API 키"), ("claude-3-5-sonnet", "Anthropic API 키")]
)
def test_get_llm_provider_cloud_requires_api_key(model, message):
    with pytest.raises(ValueError, match=message):
        llm.get_llm_provider(model)


def test_get_llm_provider_builds_cloud_providers_with_registry_repo_ids():
    with patch.object(llm, "OpenAILLMProvider", return_value="OAI") as oai, \
         patch.object(llm, "AnthropicLLMProvider", return_value="ANT") as ant:
        assert llm.get_llm_provider("gpt-4o-mini", api_key="k1") == "OAI"
        assert llm.get_llm_provider("claude-3-5-haiku", api_key="k2") == "ANT"

    oai.assert_called_once_with("gpt-4o-mini", "k1")
    ant.assert_called_once_with("claude-3-5-haiku-20241022", "k2")


def test_get_llm_provider_unsupported_backend_raises():
    registry = {"x": {"repo_id": "r", "backend": "mystery", "label": "l"}}
    with patch.object(llm, "LLM_MODEL_REGISTRY", registry):
        with pytest.raises(ValueError, match="Unsupported LLM backend"):
            llm.get_llm_provider("x")
