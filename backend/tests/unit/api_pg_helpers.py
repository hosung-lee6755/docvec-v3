"""API 엔드포인트 단위 테스트 공용 헬퍼 — 실제 Postgres(SAVEPOINT 롤백) + 데이터 팩토리.

공용 conftest의 세션 범위 엔진은 테스트별 이벤트 루프와 섞여 실패하므로(test_documents_storage_release 참고)
테스트마다 새 엔진을 쓰고, 바깥 트랜잭션을 롤백해 흔적을 남기지 않는다. 엔드포인트가 호출하는
`db.commit()`은 SAVEPOINT 해제로만 동작한다.
"""
from uuid import uuid4

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember
from app.db.models.user import User
from app.db.models.workflow import (
    WorkflowBlockInstance,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowVersion,
)
from tests.conftest import TEST_DATABASE_URL


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


async def make_user(db, role: str = "viewer", username: str | None = None) -> User:
    user = User(
        id=str(uuid4()),
        email=f"{uuid4()}@example.com",
        username=username or f"user-{uuid4().hex[:8]}",
        hashed_password="!",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def make_project(db, owner: User, name: str = "proj") -> Project:
    project = Project(id=str(uuid4()), name=name, created_by=str(owner.id))
    db.add(project)
    await db.flush()
    return project


async def add_member(db, project: Project, user: User, role: str, invited_by: User) -> None:
    db.add(ProjectMember(
        project_id=str(project.id), user_id=str(user.id), role=role, invited_by=str(invited_by.id),
    ))
    await db.flush()


async def make_collection(
    db, owner: User, project: Project | None = None, name: str = "col", **overrides
) -> Collection:
    fields = dict(
        id=str(uuid4()),
        name=name,
        qdrant_collection_name=f"col_{uuid4().hex[:12]}",
        created_by=str(owner.id),
        project_id=str(project.id) if project else None,
    )
    fields.update(overrides)
    collection = Collection(**fields)
    db.add(collection)
    await db.flush()
    return collection


async def make_document(db, owner: User, collection: Collection | None = None, **overrides) -> Document:
    fields = dict(
        id=str(uuid4()),
        filename="a.txt",
        original_filename="a.txt",
        file_size=1,
        mime_type="text/plain",
        file_hash="h" * 64,
        minio_key=f"{uuid4()}/a.txt",
        status="INDEXED",
        created_by=str(owner.id),
        collection_id=str(collection.id) if collection else None,
    )
    fields.update(overrides)
    doc = Document(**fields)
    db.add(doc)
    await db.flush()
    return doc


async def make_workflow(
    db, owner: User, project: Project | None, kind: str = "ANALYSIS", name: str = "wf"
) -> WorkflowDefinition:
    workflow = WorkflowDefinition(
        id=str(uuid4()), project_id=str(project.id) if project else None,
        name=name, kind=kind, created_by=str(owner.id),
    )
    db.add(workflow)
    await db.flush()
    return workflow


async def make_version(
    db, workflow: WorkflowDefinition, owner: User, number: int = 1, published: bool = False
) -> WorkflowVersion:
    from datetime import datetime

    version = WorkflowVersion(
        id=str(uuid4()), workflow_id=str(workflow.id), version_number=number,
        created_by=str(owner.id),
        published_at=datetime(2026, 1, 1) if published else None,
    )
    db.add(version)
    await db.flush()
    return version


async def make_block(db, version: WorkflowVersion, block_type: str, label: str | None = None,
                     config: dict | None = None) -> WorkflowBlockInstance:
    block = WorkflowBlockInstance(
        id=str(uuid4()), version_id=str(version.id), block_type=block_type,
        label=label, position={"x": 1, "y": 2}, config=config or {},
    )
    db.add(block)
    await db.flush()
    return block


async def make_edge(db, version, source, target) -> WorkflowEdge:
    edge = WorkflowEdge(
        id=str(uuid4()), version_id=str(version.id),
        from_block_id=str(source.id), to_block_id=str(target.id),
    )
    db.add(edge)
    await db.flush()
    return edge


async def make_valid_graph(db, version: WorkflowVersion):
    """ANALYSIS 워크플로우에서 validate_graph를 통과하는 최소 그래프(input → output)."""
    source = await make_block(db, version, "input", label="in")
    sink = await make_block(db, version, "output", label="out")
    await make_edge(db, version, source, sink)
    return source, sink
