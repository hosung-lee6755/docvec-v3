"""답변 스트리밍(전체 점검 2-5): 바뀐 것만 보내고, 끝나면 닫는다."""
import json

import pytest

from app.services.chat_stream import KEEPALIVE_SECONDS, POLL_SECONDS, answer_events, sse


async def _no_sleep(_seconds):
    return None


def _feed(values):
    items = iter(values)
    last = [None]

    def read():
        try:
            last[0] = next(items)
        except StopIteration:
            pass
        return last[0]

    return read


def _status_after(pending_checks, final="DONE"):
    count = [0]

    async def read():
        count[0] += 1
        return "GENERATING" if count[0] <= pending_checks else final

    return read


async def _collect(**kwargs):
    kwargs.setdefault("read_progress", lambda: None)
    kwargs.setdefault("sleep", _no_sleep)
    return [event async for event in answer_events(**kwargs)]


def _parsed(events):
    out = []
    for event in events:
        if event.startswith(":"):
            out.append(("keep-alive", None))
            continue
        name, data = event.strip().split("\n")
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_sse_keeps_korean_readable():
    assert sse("partial", {"text": "답변"}) == 'event: partial\ndata: {"text": "답변"}\n\n'


@pytest.mark.asyncio
async def test_sends_only_changed_text_then_done():
    events = await _collect(
        read_partial=_feed([None, "안녕", "안녕", "안녕하세요"]), read_status=_status_after(1),
    )

    assert _parsed(events) == [
        ("partial", {"text": "안녕"}), ("partial", {"text": "안녕하세요"}), ("done", {"status": "DONE"}),
    ]


@pytest.mark.asyncio
async def test_already_finished_message_closes_at_once():
    events = await _collect(read_partial=lambda: "남은 값", read_status=_status_after(0, final="FAILED"))

    assert _parsed(events) == [("done", {"status": "FAILED"})]


@pytest.mark.asyncio
async def test_progress_is_forwarded_when_it_changes():
    step = {"phase": "searching", "current": 1}
    events = await _collect(
        read_partial=lambda: None, read_progress=_feed([step, step]), read_status=_status_after(1),
    )

    assert _parsed(events)[0] == ("progress", step) and len(events) == 2


@pytest.mark.asyncio
async def test_quiet_stream_sends_keepalive_and_times_out():
    max_seconds = KEEPALIVE_SECONDS + POLL_SECONDS * 3
    events = await _collect(
        read_partial=lambda: None, read_status=_status_after(10**9), max_seconds=max_seconds,
    )

    assert [name for name, _ in _parsed(events)] == ["keep-alive", "timeout"]
