from datetime import timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """모든 timestamp 컬럼이 naive UTC로 저장돼 있어(DB 컬럼은 그대로
    timestamp without time zone) FastAPI가 JSON으로 낼 때 타임존 표시가
    없었다 — 프론트엔드의 new Date(...)는 타임존 표시 없는 ISO 문자열을
    UTC가 아니라 브라우저 로컬 시간대로 해석해(JS Date 스펙), 실제 시각보다
    화면에 몇 시간씩 어긋나 보이는 버그였다(2026-07-29). DB 저장 형식/마이그
    레이션 없이, 파이썬 경계에서만 tzinfo=UTC를 붙여 직렬화 시 "+00:00"이
    붙게 한다."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)
