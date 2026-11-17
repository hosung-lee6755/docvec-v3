from abc import ABC, abstractmethod
from typing import TypedDict

from app.core.config import settings


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


class LLMServerError(RuntimeError):
    """추론 서버 호출 실패. 메시지는 채팅 실패 사유로 사용자에게 그대로 보인다."""


# 예전 프로세스 안 생성(transformers)과 같은 조건: 탐욕 생성, 최대 512토큰, 반복 억제 1.15.
# 길이 하한은 두지 않는다. 하한이 있으면 짧게 끝나야 할 답이 다음 대화 차례를 지어낸다(2026-11-12).
_MAX_NEW_TOKENS = 512
_REPEAT_PENALTY = 1.15


class LLMServerProvider(LLMProvider):
    """로컬 LLM을 별도 추론 서버(Ollama)로 부른다(2026-11-13).

    워커 프로세스 안에서 LLM을 올리면 임베딩·재순위와 합쳐 GPU 약 10GB를 써서, 문서 추출과 겹치면
    12GB GPU를 넘어 Docker VM 전체가 멈출 수 있었다. 추론 서버는 4비트 양자화 모델을 요청이 있을 때
    올리고 `llm_server_keep_alive` 동안 쉬면 내린다."""

    def __init__(self, model_tag: str, transport=None) -> None:
        import httpx

        self._model_tag = model_tag
        self._client = httpx.Client(
            base_url=settings.llm_server_url,
            timeout=settings.llm_server_timeout_seconds,
            transport=transport,
        )

    def _payload(self, system_prompt: str, messages: list[dict[str, str]], stream: bool) -> dict:
        return {
            "model": self._model_tag,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": stream,
            "keep_alive": settings.llm_server_keep_alive,
            "options": {
                "temperature": 0,
                "num_predict": _MAX_NEW_TOKENS,
                "repeat_penalty": _REPEAT_PENALTY,
                "num_ctx": settings.llm_server_num_ctx,
            },
        }

    def _raise_for_status(self, response) -> None:
        if response.status_code == 404:
            raise LLMServerError(
                f"모델 {self._model_tag}이(가) 추론 서버에 없습니다. "
                f"관리자가 `docker compose exec llm ollama pull {self._model_tag}`로 받아야 합니다."
            )
        if response.status_code >= 400:
            raise LLMServerError(f"추론 서버가 오류를 돌려주었습니다(HTTP {response.status_code}).")

    def _unreachable(self) -> LLMServerError:
        return LLMServerError(f"추론 서버에 연결하지 못했습니다({settings.llm_server_url}).")

    def generate(self, system_prompt: str, messages: list[dict[str, str]]) -> str:
        import httpx

        try:
            response = self._client.post("/api/chat", json=self._payload(system_prompt, messages, False))
        except httpx.HTTPError as exc:
            raise self._unreachable() from exc
        self._raise_for_status(response)
        content = (response.json().get("message") or {}).get("content") or ""
        return _cut_template_leak(content)

    def generate_vision(
        self, system_prompt: str, image_bytes: bytes, mime_type: str, prompt: str
    ) -> str:
        """그림 한 장을 설명하게 한다(전체 점검 2-1). 추론 서버에 받아 둔 모델이 그림을 읽을 수 있는
        모델(예: qwen2.5vl, minicpm-v)일 때만 뜻이 있다. 글만 읽는 모델에 보내면 서버가 오류를 준다."""
        import base64

        import httpx

        message = {"role": "user", "content": prompt, "images": [base64.b64encode(image_bytes).decode("ascii")]}
        payload = self._payload(system_prompt, [message], False)
        if not system_prompt:
            payload["messages"] = [message]
        try:
            response = self._client.post("/api/chat", json=payload)
        except httpx.HTTPError as exc:
            raise self._unreachable() from exc
        self._raise_for_status(response)
        return _cut_template_leak((response.json().get("message") or {}).get("content") or "")

    def generate_stream(
        self, system_prompt: str, messages: list[dict[str, str]], on_delta
    ) -> str:
        import httpx

        parts: list[str] = []
        try:
            with self._client.stream(
                "POST", "/api/chat", json=self._payload(system_prompt, messages, True)
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    self._raise_for_status(response)
                for piece, done in _stream_pieces(response.iter_lines()):
                    if piece:
                        parts.append(piece)
                        _report(on_delta, _cut_template_leak("".join(parts)))
                    if done:
                        break
        except httpx.HTTPError as exc:
            raise self._unreachable() from exc
        return _cut_template_leak("".join(parts))


def _stream_pieces(lines):
    """Ollama 스트리밍 응답(줄마다 JSON 하나)에서 (새 글자, 끝 여부)를 꺼낸다."""
    import json

    for line in lines:
        if not line.strip():
            continue
        chunk = json.loads(line)
        yield (chunk.get("message") or {}).get("content") or "", bool(chunk.get("done"))


def _report(on_delta, text: str) -> None:
    try:
        on_delta(text)
    except Exception:
        pass  # 진행 표시 실패가 생성을 멈추면 안 된다


_PULLED_MODELS_TTL_SECONDS = 30
_pulled_models_cache: dict[str, tuple[float, set[str]]] = {}


def pulled_local_models(transport=None) -> set[str]:
    """추론 서버에 받아 둔 모델 태그 목록. 서버가 꺼져 있으면 빈 집합이라 채팅 화면에서 '사용 불가'로 보인다.
    채팅 화면이 열릴 때마다 서버를 부르지 않도록 30초 동안 결과를 재사용한다."""
    import time

    import httpx

    cached = _pulled_models_cache.get("tags")
    if cached and time.monotonic() - cached[0] < _PULLED_MODELS_TTL_SECONDS:
        return cached[1]
    try:
        with httpx.Client(base_url=settings.llm_server_url, timeout=2.0, transport=transport) as client:
            response = client.get("/api/tags")
            response.raise_for_status()
            names = {m.get("name", "") for m in response.json().get("models", [])}
    except (httpx.HTTPError, ValueError):
        names = set()
    _pulled_models_cache["tags"] = (time.monotonic(), names)
    return names


class OpenAILLMProvider(LLMProvider):
    def __init__(self, model: str, api_key: str, base_url: str | None = None) -> None:
        from openai import OpenAI

        # base_url을 주면 OpenAI와 같은 API를 쓰는 사내 추론 서버(vLLM 등)로 보낸다(전체 점검 2-3)
        self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
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


class LLMModelSpec(TypedDict, total=False):
    repo_id: str
    backend: str
    label: str
    # backend가 "openai_compatible"일 때 추론 서버 주소(예: http://gpu-server:8000/v1)
    base_url: str


# Curated model set — see plan doc Phase 5-B. "local" 모델은 사내 추론 서버(Ollama)가 돌린다.
# repo_id는 Ollama 모델 태그다(4비트 양자화, 3B 약 2.5GB·7B 약 5.5GB). 새 태그는 배포 때
# `docker compose exec llm ollama pull <태그>`로 받아 둔다(2026-11-13, 예전에는 워커 안 transformers).
_BUILTIN_MODELS: dict[str, LLMModelSpec] = {
    "qwen2.5-3b": {
        "repo_id": "qwen2.5:3b-instruct-q4_K_M",
        "backend": "local",
        "label": "Qwen2.5 3B Instruct (로컬)",
    },
    "qwen2.5-7b": {
        "repo_id": "qwen2.5:7b-instruct-q4_K_M",
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

# 설정으로 더하는 모델(전체 점검 2-3). 코드를 고치지 않고 .env의 LLM_EXTRA_MODELS에 JSON 목록으로 적는다.
#   [{"key": "exaone-7.8b", "repo_id": "exaone3.5:7.8b", "backend": "local", "label": "EXAONE 3.5 7.8B (로컬)"},
#    {"key": "qwen-14b", "repo_id": "Qwen/Qwen2.5-14B-Instruct", "backend": "openai_compatible",
#     "label": "Qwen2.5 14B (사내 GPU 서버)", "base_url": "http://gpu-server:8000/v1"}]
# "local"은 Ollama 태그이고, "openai_compatible"은 OpenAI와 같은 API를 쓰는 사내 추론 서버다. 두 가지만 받는다.
# 외부 클라우드 모델은 보안등급 차단(external_model_policy)과 요금 계산이 묶여 있어 설정으로 더하지 않는다.
# openai_compatible의 주소는 반드시 사내 서버여야 한다. 문서 내용이 등급과 상관없이 그 서버로 간다.
CONFIGURABLE_BACKENDS = frozenset({"local", "openai_compatible"})


def parse_extra_models(raw: str | None, existing: dict[str, LLMModelSpec]) -> dict[str, LLMModelSpec]:
    """LLM_EXTRA_MODELS를 읽는다. 잘못된 항목은 건너뛰고 로그를 남긴다(설정 실수로 서비스가 죽지 않게)."""
    import json
    import logging

    log = logging.getLogger(__name__)
    if not raw or not raw.strip():
        return {}
    try:
        items = json.loads(raw)
    except ValueError:
        log.error("LLM_EXTRA_MODELS is not valid JSON; ignoring it")
        return {}
    if not isinstance(items, list):
        log.error("LLM_EXTRA_MODELS must be a JSON list; ignoring it")
        return {}
    models: dict[str, LLMModelSpec] = {}
    for item in items:
        problem = _extra_model_problem(item, {*existing, *models})
        if problem:
            log.error("LLM_EXTRA_MODELS entry skipped (%s): %r", problem, item)
            continue
        spec: LLMModelSpec = {"repo_id": item["repo_id"], "backend": item["backend"], "label": item["label"]}
        if item["backend"] == "openai_compatible":
            spec["base_url"] = item["base_url"]
        models[item["key"]] = spec
    return models


def _extra_model_problem(item, taken: set[str]) -> str | None:
    if not isinstance(item, dict):
        return "not an object"
    for name in ("key", "repo_id", "backend", "label"):
        if not isinstance(item.get(name), str) or not item[name].strip():
            return f"missing {name}"
    if item["key"] in taken:
        return "key already used"
    if item["backend"] not in CONFIGURABLE_BACKENDS:
        return "backend must be local or openai_compatible"
    if item["backend"] == "openai_compatible":
        base_url = item.get("base_url")
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            return "openai_compatible needs an http(s) base_url"
    return None


def _build_registry() -> dict[str, LLMModelSpec]:
    from app.core.config import settings

    return {**_BUILTIN_MODELS, **parse_extra_models(settings.llm_extra_models, _BUILTIN_MODELS)}


LLM_MODEL_REGISTRY: dict[str, LLMModelSpec] = _build_registry()

# Only the local backend is cached (one HTTP client per model tag) — cloud providers are cheap to instantiate per
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
            _local_provider_cache[model_key] = LLMServerProvider(spec["repo_id"])
        return _local_provider_cache[model_key]
    if spec["backend"] == "openai_compatible":
        from app.core.config import settings

        if model_key not in _local_provider_cache:
            # 키를 받지 않는 서버도 SDK는 빈 값을 거부하므로 자리만 채운다
            _local_provider_cache[model_key] = OpenAILLMProvider(
                spec["repo_id"], settings.llm_compatible_api_key or "not-needed", base_url=spec["base_url"],
            )
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
