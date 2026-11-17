"""답변 스트리밍(전체 점검 2-5, 2026-11-16).

워커는 만들고 있는 답변을 Redis(chat_partial:<id>)에 계속 덮어쓴다. 예전에는 화면이 1.5초마다 메시지를
다시 읽어 그 값을 보여 줬다. 여기서는 연결 하나를 열어 두고 값이 바뀔 때마다 바로 밀어 준다(SSE).

이벤트
- partial: {"text": 지금까지의 답변 전체}. 조각이 아니라 전체를 보내므로 하나를 놓쳐도 다음 것으로 맞는다.
- progress: 심층 검색 진행 상태(chat_progress:<id>의 내용 그대로).
- done: {"status": "DONE" 또는 "FAILED"}. 화면은 이때 메시지를 다시 읽어 최종 답변과 인용을 받는다.
- timeout: 정해 둔 시간 안에 끝나지 않았다. 화면은 기존 주기 조회로 이어 간다.

읽는 함수들을 밖에서 받으므로 Redis나 DB 없이 시험할 수 있다.
"""
import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

POLL_SECONDS = 0.15
STATUS_CHECK_SECONDS = 1.0
KEEPALIVE_SECONDS = 15.0
MAX_STREAM_SECONDS = 600.0
PENDING_STATUSES = frozenset({"PENDING", "GENERATING"})

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    # nginx가 응답을 모았다가 한꺼번에 보내지 않게 한다
    "X-Accel-Buffering": "no",
}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def answer_events(
    *,
    read_partial: Callable[[], str | None],
    read_progress: Callable[[], dict | None],
    read_status: Callable[[], Awaitable[str | None]],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_seconds: float = MAX_STREAM_SECONDS,
) -> AsyncIterator[str]:
    last_text: str | None = None
    last_progress: dict | None = None
    elapsed = 0.0
    since_status = STATUS_CHECK_SECONDS  # 첫 바퀴에 바로 상태를 본다
    since_output = 0.0
    while elapsed < max_seconds:
        if since_status >= STATUS_CHECK_SECONDS:
            since_status = 0.0
            status = await read_status()
            if status not in PENDING_STATUSES:
                # 지워진 메시지(None)도 여기로 온다. 화면이 다시 읽으면 404로 알게 된다
                yield sse("done", {"status": status})
                return
        text = read_partial()
        if text and text != last_text:
            last_text = text
            since_output = 0.0
            yield sse("partial", {"text": text})
        progress = read_progress()
        if progress and progress != last_progress:
            last_progress = progress
            since_output = 0.0
            yield sse("progress", progress)
        if since_output >= KEEPALIVE_SECONDS:
            since_output = 0.0
            yield ": keep-alive\n\n"
        await sleep(POLL_SECONDS)
        elapsed += POLL_SECONDS
        since_status += POLL_SECONDS
        since_output += POLL_SECONDS
    yield sse("timeout", {})
