from abc import ABC, abstractmethod
from typing import TypedDict


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str: ...

    def generate_stream(
        self, system_prompt: str, messages: list[dict[str, str]], on_delta
    ) -> str:
        """Generates while invoking on_delta(text_so_far) as output grows, and
        returns the final text. Default: no true streaming — generate fully,
        then emit once (cloud providers are fast enough that partial display
        matters mainly for the slow local model, which overrides this)."""
        text = self.generate(system_prompt, messages)
        on_delta(text)
        return text

    def generate_vision(
        self, system_prompt: str, image_bytes: bytes, mime_type: str, prompt: str
    ) -> str:
        """Extract/describe content from a single image. Only cloud providers with
        vision-capable models implement this — the local model has no vision head."""
        raise NotImplementedError(f"{type(self).__name__} does not support vision input")


# 대화 템플릿 표지. 특수 토큰으로 지워지지 않는 것(<tool_call>)도 있어 문자열로 자른다.
# 답 뒤에 이 표지가 나오면 모델이 다음 차례(user 질문, 발췌문)를 지어내기 시작한 것이다.
_TEMPLATE_LEAK_MARKERS = ("<tool_call>", "<|im_start|>", "<|im_end|>", "<|endoftext|>")


def _cut_template_leak(text: str) -> str:
    positions = [i for i in (text.find(m) for m in _TEMPLATE_LEAK_MARKERS) if i >= 0]
    return text[: min(positions)].rstrip() if positions else text


class LocalLLMProvider(LLMProvider):
    def __init__(self, repo_id: str) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        # float16 halves VRAM/bandwidth on GPU with negligible quality loss for
        # inference; CPU has no tensor-core benefit from fp16 so keep it at fp32.
        dtype = torch.float16 if self._device == "cuda" else torch.float32
        self._tokenizer = AutoTokenizer.from_pretrained(repo_id)
        self._model = AutoModelForCausalLM.from_pretrained(repo_id, torch_dtype=dtype).to(
            self._device
        )

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        full_messages = [{"role": "system", "content": system_prompt}, *messages]
        prompt_text = self._tokenizer.apply_chat_template(
            full_messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(prompt_text, return_tensors="pt").to(self._device)
        outputs = self._model.generate(
            **inputs,
            max_new_tokens=512,
            # 길이 하한(min_new_tokens)은 두지 않는다. 하한이 있으면 "알 수 없습니다"처럼
            # 짧게 끝나야 할 답이 끝을 못 내고 다음 대화 차례를 지어낸다. "[1]"만 내는
            # 출력은 generate_answer의 _is_degenerate_answer가 다시 생성시킨다.
            repetition_penalty=1.15,
            do_sample=False,
        )
        generated = outputs[0][inputs["input_ids"].shape[-1] :]
        return _cut_template_leak(self._tokenizer.decode(generated, skip_special_tokens=True))

    def generate_stream(
        self, system_prompt: str, messages: list[dict[str, str]], on_delta
    ) -> str:
        """True token streaming for the local model: generation runs on a
        worker thread while this thread drains the streamer and reports the
        accumulated text via on_delta. Same generation parameters as generate()."""
        from threading import Thread

        from transformers import TextIteratorStreamer

        full_messages = [{"role": "system", "content": system_prompt}, *messages]
        prompt_text = self._tokenizer.apply_chat_template(
            full_messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(prompt_text, return_tensors="pt").to(self._device)
        streamer = TextIteratorStreamer(
            self._tokenizer, skip_prompt=True, skip_special_tokens=True
        )
        thread = Thread(
            target=self._model.generate,
            kwargs=dict(
                **inputs,
                max_new_tokens=512,
                repetition_penalty=1.15,
                do_sample=False,
                streamer=streamer,
            ),
        )
        thread.start()
        parts: list[str] = []
        for piece in streamer:
            parts.append(piece)
            try:
                on_delta(_cut_template_leak("".join(parts)))
            except Exception:
                pass  # partial-progress reporting must never kill generation
        thread.join()
        return _cut_template_leak("".join(parts))


class OpenAILLMProvider(LLMProvider):
    def __init__(self, model: str, api_key: str) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model
        # Populated after each generate() call so callers can log token usage
        # for cost tracking -- None until the first call completes.
        self.last_usage: dict[str, int] | None = None

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system_prompt}, *messages],
        )
        if response.usage:
            self.last_usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        return response.choices[0].message.content or ""

    def generate_vision(
        self, system_prompt: str, image_bytes: bytes, mime_type: str, prompt: str
    ) -> str:
        import base64

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                    ],
                },
            ],
        )
        return response.choices[0].message.content or ""


class AnthropicLLMProvider(LLMProvider):
    def __init__(self, model: str, api_key: str) -> None:
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model
        self.last_usage: dict[str, int] | None = None

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        if response.usage:
            self.last_usage = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        return "".join(block.text for block in response.content if block.type == "text")

    def generate_vision(
        self, system_prompt: str, image_bytes: bytes, mime_type: str, prompt: str
    ) -> str:
        import base64

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        return "".join(block.text for block in response.content if block.type == "text")


class LLMModelSpec(TypedDict):
    repo_id: str
    backend: str
    label: str


# Curated model set — see plan doc Phase 5-B. Local models require the `embed`
# poetry group (torch/transformers, worker-only) and are downloaded on demand into
# the shared HF_HOME model cache the first time they're selected.
LLM_MODEL_REGISTRY: dict[str, LLMModelSpec] = {
    "qwen2.5-3b": {
        "repo_id": "Qwen/Qwen2.5-3B-Instruct",
        "backend": "local",
        "label": "Qwen2.5 3B Instruct (로컬)",
    },
    "qwen2.5-7b": {
        "repo_id": "Qwen/Qwen2.5-7B-Instruct",
        "backend": "local",
        "label": "Qwen2.5 7B Instruct (로컬)",
    },
    "gpt-4o-mini": {
        "repo_id": "gpt-4o-mini",
        "backend": "openai",
        "label": "GPT-4o mini (OpenAI)",
    },
    "gpt-4o": {
        "repo_id": "gpt-4o",
        "backend": "openai",
        "label": "GPT-4o (OpenAI)",
    },
    "claude-3-5-haiku": {
        "repo_id": "claude-3-5-haiku-20241022",
        "backend": "anthropic",
        "label": "Claude 3.5 Haiku (Anthropic)",
    },
    "claude-3-5-sonnet": {
        "repo_id": "claude-3-5-sonnet-20241022",
        "backend": "anthropic",
        "label": "Claude 3.5 Sonnet (Anthropic)",
    },
}

# Only the local backend is cached — cloud providers are cheap to instantiate per
# request and are keyed by the calling user's own API key, so caching them would
# either leak one user's client across requests or require a cache key per user.
_local_provider_cache: dict[str, LLMProvider] = {}

# USD per 1M tokens, publicly listed provider rates as of this writing -- approximate,
# for the usage dashboard's cost estimate only, not a billing-grade computation.
_TOKEN_PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
}


def estimate_cost_usd(model_key: str, input_tokens: int, output_tokens: int) -> float:
    pricing = _TOKEN_PRICING_PER_MILLION.get(model_key)
    if pricing is None:
        return 0.0
    input_rate, output_rate = pricing
    return (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate


def get_llm_provider(model_key: str, api_key: str | None = None) -> LLMProvider:
    spec = LLM_MODEL_REGISTRY.get(model_key)
    if spec is None:
        raise ValueError(f"Unknown LLM model: {model_key}")

    if spec["backend"] == "local":
        if model_key not in _local_provider_cache:
            _local_provider_cache[model_key] = LocalLLMProvider(spec["repo_id"])
        return _local_provider_cache[model_key]
    if spec["backend"] == "openai":
        if not api_key:
            raise ValueError("OpenAI API 키가 등록되어 있지 않습니다")
        return OpenAILLMProvider(spec["repo_id"], api_key)
    if spec["backend"] == "anthropic":
        if not api_key:
            raise ValueError("Anthropic API 키가 등록되어 있지 않습니다")
        return AnthropicLLMProvider(spec["repo_id"], api_key)
    raise ValueError(f"Unsupported LLM backend: {spec['backend']}")
