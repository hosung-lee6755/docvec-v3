"""문서 상태 전이의 원자적 선점.

"상태를 확인한 뒤 바꾸는" 두 단계는 동시 요청(두 번 클릭, 여러 탭, 컬렉션 일괄 재처리와
개별 재처리)에서 같은 작업을 두 번 디스패치한다. 확인과 변경을 한 UPDATE로 묶어
한 요청만 통과시킨다.
"""
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document


async def claim_document_status(
    db: AsyncSession,
    document_id: UUID | str,
    expected: str | Sequence[str],
    new_status: str,
    **extra_values,
) -> bool:
    """`status`가 `expected`(하나 또는 여러 개)인 문서만 `new_status`로 바꾼다. 바뀌었으면 True.

    commit/rollback은 호출자가 한다(같은 트랜잭션에서 나머지 쓰기를 함께 묶기 위해).
    세션 안 객체를 동기화/만료시키지 않는다 — 비동기 세션에서 만료된 속성을 읽으면
    MissingGreenlet이 나므로, 이후 객체가 필요한 호출자는 명시적으로 refresh한다."""
    expected_statuses = [expected] if isinstance(expected, str) else list(expected)
    result = await db.execute(
        update(Document)
        .where(Document.id == document_id, Document.status.in_(expected_statuses))
        .values(status=new_status, updated_at=datetime.utcnow(), **extra_values)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
