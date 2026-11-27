"""검색 결과와 채팅 인용이 함께 쓰는 출처 위치 정보(2026-11-27).

벡터 DB 페이로드에는 문서 이름, 컬렉션 id, 시작 쪽만 있다. 프로젝트·컬렉션 이름과 절 경로, 끝 쪽은
Postgres 에서 한 번에 읽어 붙인다. 색인을 다시 만들지 않아도 예전에 만든 결과에도 붙는다.
"""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.collection import Collection
from app.db.models.document_chunk import DocumentChunk
from app.db.models.project import Project


@dataclass(frozen=True)
class CollectionPlace:
    collection_name: str | None
    project_id: str | None
    project_name: str | None


@dataclass(frozen=True)
class ChunkPlace:
    section_path: list[str] | None
    page_start: int | None
    page_end: int | None


def _uuids(values) -> list[UUID]:
    out: list[UUID] = []
    for value in values:
        try:
            out.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return out


async def collection_places(db: AsyncSession, collection_ids) -> dict[str, CollectionPlace]:
    """컬렉션 id -> (컬렉션 이름, 프로젝트 id, 프로젝트 이름). 프로젝트 밖 컬렉션은 프로젝트가 비어 있다."""
    ids = _uuids(set(collection_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Collection.id, Collection.name, Collection.project_id, Project.name)
            .outerjoin(Project, Project.id == Collection.project_id)
            .where(Collection.id.in_(ids))
        )
    ).all()
    return {
        str(cid): CollectionPlace(name, str(pid) if pid else None, pname)
        for cid, name, pid, pname in rows
    }


async def chunk_places(db: AsyncSession, owners: dict[str, str]) -> dict[str, ChunkPlace]:
    """청크 id -> (절 경로, 시작 쪽, 끝 쪽). owners 는 청크 id -> 문서 id 이고, 다른 문서의 청크는 버린다."""
    ids = _uuids(owners)
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(DocumentChunk.id, DocumentChunk.document_id, DocumentChunk.section_path,
                   DocumentChunk.page_start, DocumentChunk.page_end)
            .where(DocumentChunk.id.in_(ids))
        )
    ).all()
    return {
        str(r.id): ChunkPlace(r.section_path or None, r.page_start, r.page_end)
        for r in rows
        if str(r.document_id) == str(owners.get(str(r.id)))
    }
