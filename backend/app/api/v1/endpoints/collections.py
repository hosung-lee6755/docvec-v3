from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import accessible_project_ids, check_collection_access, check_project_access
from app.core.config import settings
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from app.db.models.collection import Collection
from app.db.models.collection_member import CollectionMember
from app.db.models.document import Document
from app.db.models.golden_eval_run import GoldenEvalRun
from app.db.models.golden_query import GoldenQuery
from app.db.models.processing_job import ProcessingJob
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStep
from app.db.session import get_db
from app.services.document_state import claim_document_status
from app.services.document_storage import release_original
from app.services.embedding import EMBEDDING_MODEL_REGISTRY

router = APIRouter()

_SELECTABLE_MODELS = {
    key: spec
    for key, spec in EMBEDDING_MODEL_REGISTRY.items()
    # All collections currently share one physical Qdrant collection with a fixed
    # vector size (see settings.default_embedding_dimension), so only models that
    # produce that exact dimension can be safely selected without a storage crash.
    if spec["backend"] != "mock" and spec["dimension"] == settings.default_embedding_dimension
}


def _validate_embedding_model(v: str) -> str:
    if v not in _SELECTABLE_MODELS:
        raise ValueError(f"embedding_model must be one of {sorted(_SELECTABLE_MODELS)}")
    return v


class CollectionCreate(BaseModel):
    name: str
    description: str | None = None
    project_id: UUID | None = None
    embedding_model: str = settings.default_embedding_model
    chunk_max_tokens: int = settings.default_chunk_max_tokens
    chunk_min_tokens: int = settings.default_chunk_min_tokens
    chunk_overlap_tokens: int = settings.default_chunk_overlap_tokens
    chunk_strategy: Literal["size", "semantic"] = "size"
    # 전처리/분석 워크플로우도 컬렉션 생성 시점에 바로 지정할 수 있다.
    # 워크플로우가 프로젝트 단위로 생성되는 구조이므로, 생성 후 수정 화면을
    # 따로 열 필요 없이 처음부터 선택 가능하다.
    default_workflow_id: UUID | None = None
    default_workflow_version: int | None = None
    default_analysis_workflow_id: UUID | None = None
    default_analysis_workflow_version: int | None = None

    _validate_model = field_validator("embedding_model")(_validate_embedding_model)


class CollectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    project_id: UUID | None = None
    restrict_to_members: bool | None = None
    embedding_model: str | None = None
    chunk_max_tokens: int | None = None
    chunk_min_tokens: int | None = None
    chunk_overlap_tokens: int | None = None
    chunk_strategy: Literal["size", "semantic"] | None = None
    # 이 컬렉션에 업로드되는 문서에 기본 적용할 전처리 워크플로우 — null이면
    # 시스템 표준 워크플로우 사용. clear_default_workflow가 true면 두 필드를
    # 명시적으로 null로 되돌린다(그냥 default_workflow_id=None만으로는 "값을
    # 안 보냄"과 "null로 지운다"를 Pydantic의 exclude_unset으로 구분할 수 없어서).
    default_workflow_id: UUID | None = None
    default_workflow_version: int | None = None
    clear_default_workflow: bool = False
    default_analysis_workflow_id: UUID | None = None
    default_analysis_workflow_version: int | None = None
    clear_default_analysis_workflow: bool = False

    _validate_model = field_validator("embedding_model")(
        lambda v: _validate_embedding_model(v) if v is not None else v
    )


class MemberInvite(BaseModel):
    email: str
    role: Literal["viewer", "editor"] = "viewer"


class CollectionResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    project_id: UUID | None
    restrict_to_members: bool
    qdrant_collection_name: str
    embedding_model: str
    chunk_max_tokens: int
    chunk_min_tokens: int
    chunk_overlap_tokens: int
    chunk_strategy: str
    default_workflow_id: UUID | None = None
    default_workflow_version: int | None = None
    default_analysis_workflow_id: UUID | None = None
    default_analysis_workflow_version: int | None = None
    reembed_status: str | None = None
    reembed_progress: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/embedding-models")
async def list_embedding_models(
    current_user: User = Depends(get_current_user),
):
    return {
        "items": [
            {"key": key, "label": spec["label"], "dimension": spec["dimension"]}
            for key, spec in _SELECTABLE_MODELS.items()
            if key != "openai" or settings.openai_api_key
        ]
    }


@router.post("", response_model=CollectionResponse)
async def create_collection(
    data: CollectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.project_id is not None:
        await check_project_access(db, data.project_id, current_user, min_role="editor")

    from app.db.models.workflow import WorkflowDefinition

    if data.default_workflow_id is not None:
        workflow = await db.get(WorkflowDefinition, data.default_workflow_id)
        if workflow is None or workflow.kind != "PREPROCESS":
            raise HTTPException(status_code=400, detail="전처리(PREPROCESS) 워크플로우만 기본값으로 지정할 수 있습니다")
    if data.default_analysis_workflow_id is not None:
        analysis_workflow = await db.get(WorkflowDefinition, data.default_analysis_workflow_id)
        if analysis_workflow is None or analysis_workflow.kind != "ANALYSIS":
            raise HTTPException(status_code=400, detail="분석(ANALYSIS) 워크플로우만 기본값으로 지정할 수 있습니다")

    collection = Collection(
        name=data.name,
        description=data.description,
        project_id=str(data.project_id) if data.project_id else None,
        qdrant_collection_name=data.name.lower().replace(" ", "_"),
        embedding_model=data.embedding_model,
        chunk_max_tokens=data.chunk_max_tokens,
        chunk_min_tokens=data.chunk_min_tokens,
        chunk_overlap_tokens=data.chunk_overlap_tokens,
        chunk_strategy=data.chunk_strategy,
        default_workflow_id=str(data.default_workflow_id) if data.default_workflow_id else None,
        default_workflow_version=data.default_workflow_version,
        default_analysis_workflow_id=(
            str(data.default_analysis_workflow_id) if data.default_analysis_workflow_id else None
        ),
        default_analysis_workflow_version=data.default_analysis_workflow_version,
        created_by=str(current_user.id),
    )
    db.add(collection)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="이미 동일한 이름의 컬렉션이 있습니다",
        )
    await db.refresh(collection)
    return collection


@router.get("")
async def list_collections(
    project_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member_roles_result = await db.execute(
        select(CollectionMember.collection_id, CollectionMember.role).where(
            CollectionMember.user_id == str(current_user.id)
        )
    )
    member_roles = dict(member_roles_result.all())

    project_ids = await accessible_project_ids(db, current_user)
    project_member_roles = dict(
        (
            await db.execute(
                select(ProjectMember.project_id, ProjectMember.role).where(
                    ProjectMember.user_id == str(current_user.id)
                )
            )
        ).all()
    )
    owned_project_ids = set(
        (await db.scalars(select(Project.id).where(Project.created_by == str(current_user.id)))).all()
    )

    filters = [Collection.created_by == str(current_user.id)]
    if member_roles:
        filters.append(Collection.id.in_(member_roles.keys()))
    if project_ids:
        filters.append(
            Collection.project_id.in_(project_ids) & Collection.restrict_to_members.is_(False)
        )
    scope = [or_(*filters)]
    if project_id is not None:
        scope.append(Collection.project_id == project_id)
    result = await db.execute(select(Collection).where(*scope))
    collections = result.scalars().all()

    project_names: dict[str, str] = {}
    project_col_ids = {c.project_id for c in collections if c.project_id}
    if project_col_ids:
        rows = (
            await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_col_ids)))
        ).all()
        project_names = {str(row[0]): row[1] for row in rows}

    def _role_for(c: Collection) -> str | None:
        if str(c.created_by) == str(current_user.id):
            return "owner"
        if c.id in member_roles:
            return member_roles[c.id]
        if c.project_id and not c.restrict_to_members:
            if c.project_id in owned_project_ids:
                return "editor"
            return project_member_roles.get(c.project_id)
        return None

    counts_result = await db.execute(
        select(Document.collection_id, func.count(Document.id)).group_by(Document.collection_id)
    )
    counts = dict(counts_result.all())
    items = [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "project_id": c.project_id,
            "project_name": project_names.get(str(c.project_id)) if c.project_id else None,
            "restrict_to_members": c.restrict_to_members,
            "qdrant_collection_name": c.qdrant_collection_name,
            "embedding_model": c.embedding_model,
            "chunk_max_tokens": c.chunk_max_tokens,
            "chunk_min_tokens": c.chunk_min_tokens,
            "chunk_overlap_tokens": c.chunk_overlap_tokens,
            "reembed_status": c.reembed_status,
            "reembed_progress": c.reembed_progress,
            "default_workflow_id": c.default_workflow_id,
            "default_workflow_version": c.default_workflow_version,
            "default_analysis_workflow_id": c.default_analysis_workflow_id,
            "default_analysis_workflow_version": c.default_analysis_workflow_version,
            "created_at": c.created_at,
            "document_count": counts.get(c.id, 0),
            "is_owner": str(c.created_by) == str(current_user.id),
            "role": _role_for(c),
        }
        for c in collections
    ]
    return {"items": items}


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await check_collection_access(db, collection_id, current_user, min_role="viewer")


@router.get("/{collection_id}/vector-stats")
async def get_collection_vector_stats(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    collection = await check_collection_access(db, collection_id, current_user, min_role="viewer")

    from app.services.qdrant_service import qdrant_service

    total_documents = await db.scalar(
        select(func.count(Document.id)).where(Document.collection_id == collection_id)
    ) or 0
    indexed_documents = await db.scalar(
        select(func.count(Document.id)).where(
            Document.collection_id == collection_id, Document.status == "INDEXED"
        )
    ) or 0
    total_vectors = qdrant_service.count_by_collection(
        settings.qdrant_collection_name, str(collection_id)
    )
    spec = EMBEDDING_MODEL_REGISTRY.get(collection.embedding_model)

    return {
        "embedding_model": collection.embedding_model,
        "embedding_model_label": spec["label"] if spec else collection.embedding_model,
        "dimension": spec["dimension"] if spec else None,
        "total_documents": total_documents,
        "indexed_documents": indexed_documents,
        "total_vectors": total_vectors,
        "reembed_status": collection.reembed_status,
        "reembed_progress": collection.reembed_progress,
    }


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: UUID,
    data: CollectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    collection = await check_collection_access(db, collection_id, current_user, min_role="editor")
    if data.name is not None:
        collection.name = data.name
    if data.description is not None:
        collection.description = data.description
    if data.project_id is not None:
        await check_project_access(db, data.project_id, current_user, min_role="editor")
        collection.project_id = str(data.project_id)
    if data.restrict_to_members is not None:
        collection.restrict_to_members = data.restrict_to_members
    if data.embedding_model is not None and data.embedding_model != collection.embedding_model:
        if collection.reembed_status == "RUNNING":
            raise HTTPException(
                status_code=409,
                detail="이미 재임베딩이 진행 중입니다. 완료된 후 다시 시도하세요.",
            )
        doc_count = await db.scalar(
            select(func.count(Document.id)).where(Document.collection_id == collection_id)
        )
        collection.embedding_model = data.embedding_model
        if doc_count:
            # Existing chunks stay embedded with the OLD model until the
            # background job below re-embeds them — search/chat may briefly mix
            # old- and new-model vectors while reembed_status is RUNNING. Same
            # tradeoff as any live re-embed: there's no way to atomically swap
            # every vector at once.
            from app.pipeline.tasks.reembed import reembed_collection

            collection.reembed_status = "PENDING"
            collection.reembed_progress = f"0/{doc_count}"
            await db.commit()
            reembed_collection.delay(str(collection_id), data.embedding_model)
        else:
            collection.reembed_status = None
            collection.reembed_progress = None
    if data.chunk_max_tokens is not None:
        collection.chunk_max_tokens = data.chunk_max_tokens
    if data.chunk_min_tokens is not None:
        collection.chunk_min_tokens = data.chunk_min_tokens
    if data.chunk_overlap_tokens is not None:
        collection.chunk_overlap_tokens = data.chunk_overlap_tokens
    if data.chunk_strategy is not None:
        collection.chunk_strategy = data.chunk_strategy

    if data.clear_default_workflow:
        collection.default_workflow_id = None
        collection.default_workflow_version = None
    elif data.default_workflow_id is not None:
        from app.db.models.workflow import WorkflowDefinition

        workflow = await db.get(WorkflowDefinition, data.default_workflow_id)
        if workflow is None or workflow.kind != "PREPROCESS":
            raise HTTPException(status_code=400, detail="전처리(PREPROCESS) 워크플로우만 기본값으로 지정할 수 있습니다")
        collection.default_workflow_id = str(data.default_workflow_id)
        collection.default_workflow_version = data.default_workflow_version

    if data.clear_default_analysis_workflow:
        collection.default_analysis_workflow_id = None
        collection.default_analysis_workflow_version = None
    elif data.default_analysis_workflow_id is not None:
        from app.db.models.workflow import WorkflowDefinition

        analysis_workflow = await db.get(WorkflowDefinition, data.default_analysis_workflow_id)
        if analysis_workflow is None or analysis_workflow.kind != "ANALYSIS":
            raise HTTPException(status_code=400, detail="분석(ANALYSIS) 워크플로우만 기본값으로 지정할 수 있습니다")
        collection.default_analysis_workflow_id = str(data.default_analysis_workflow_id)
        collection.default_analysis_workflow_version = data.default_analysis_workflow_version

    await db.commit()
    await db.refresh(collection)
    return collection


async def cascade_delete_collection(db: AsyncSession, collection: Collection) -> None:
    """Delete a collection and everything that FKs into it (no ON DELETE CASCADE
    exists at the DB level for any of these), including each document's Qdrant
    vectors and MinIO file. Caller is responsible for the access check and commit.
    """
    from app.services.qdrant_service import qdrant_service
    from app.services.storage import storage_service

    docs = (
        await db.scalars(select(Document).where(Document.collection_id == collection.id))
    ).all()
    doc_ids = [doc.id for doc in docs]
    if doc_ids:
        await db.execute(delete(ProcessingJob).where(ProcessingJob.document_id.in_(doc_ids)))

    # workflow_runs.document_id/collection_id and workflow_run_steps.run_id carry no
    # ON DELETE CASCADE (unlike every other document/run-scoped table), so they must
    # be cleared manually. A run can reference this collection directly (e.g. a
    # COLLECTION_REPROCESS trigger) with no document_id at all, so match on both.
    run_conditions = [WorkflowRun.collection_id == collection.id]
    if doc_ids:
        run_conditions.append(WorkflowRun.document_id.in_(doc_ids))
    run_ids_subq = select(WorkflowRun.id).where(or_(*run_conditions))
    await db.execute(delete(WorkflowRunStep).where(WorkflowRunStep.run_id.in_(run_ids_subq)))
    await db.execute(delete(WorkflowRun).where(or_(*run_conditions)))

    # chat_conversations.collection_id and chat_messages.conversation_id are in the
    # same boat — no ON DELETE CASCADE.
    conv_ids_subq = select(ChatConversation.id).where(ChatConversation.collection_id == collection.id)
    await db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conv_ids_subq)))
    await db.execute(delete(ChatConversation).where(ChatConversation.collection_id == collection.id))

    for doc in docs:
        qdrant_service.delete_by_document(settings.qdrant_collection_name, str(doc.id))
        # 같은 원본 키를 다른 컬렉션의 문서가 참조하면 객체를 남긴다(이 컬렉션 문서는 제외).
        await release_original(
            db, storage_service, settings.minio_bucket_originals, doc.minio_key,
            exclude_document_ids=doc_ids,
        )
        await db.delete(doc)

    # golden_queries.collection_id and golden_eval_runs.collection_id — same gap.
    await db.execute(delete(GoldenEvalRun).where(GoldenEvalRun.collection_id == collection.id))
    await db.execute(delete(GoldenQuery).where(GoldenQuery.collection_id == collection.id))

    await db.execute(delete(CollectionMember).where(CollectionMember.collection_id == collection.id))

    # No SQLAlchemy relationship() links Document -> Collection, so the unit-of-work
    # flush order isn't guaranteed to delete documents before the collection. Force
    # the document deletes to hit the DB now so the FK is already satisfied when the
    # collection delete flushes.
    await db.flush()
    await db.delete(collection)


@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    collection = await db.scalar(
        select(Collection).where(Collection.id == collection_id)
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    # 관리자는 소유자가 아니어도 삭제 가능 — delete_project와 동일한 이유
    # (2026-07-29).
    if str(collection.created_by) != str(current_user.id) and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    await cascade_delete_collection(db, collection)
    await db.commit()
    return {"message": "Collection deleted"}


@router.post("/{collection_id}/reprocess")
async def reprocess_collection(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.pipeline.tasks.process import continue_processing

    # 소유자뿐 아니라 편집 권한이 있는 멤버(프로젝트/컬렉션 editor)도 재처리할 수 있다.
    await check_collection_access(db, collection_id, current_user, min_role="editor")

    docs = (
        await db.scalars(
            select(Document).where(
                Document.collection_id == collection_id,
                Document.status.in_(["INDEXED", "FAILED"]),
            )
        )
    ).all()

    # A document that failed before parsing has no parsed_text to re-chunk/re-embed
    # from — reprocessing it would just re-run chunking on an empty string. Skip
    # those rather than silently "succeeding" with 0 chunks.
    reprocessable = [doc for doc in docs if doc.parsed_text]
    skipped = len(docs) - len(reprocessable)

    # 문서별로 원자적으로 선점한 것만 디스패치한다 — 같은 시점에 개별 재처리/다른 일괄
    # 재처리가 이미 잡은 문서는 건너뛰어 중복 실행을 막는다.
    claimed_ids: list[str] = []
    for doc in reprocessable:
        if await claim_document_status(db, doc.id, ("INDEXED", "FAILED"), "CHUNKING"):
            claimed_ids.append(str(doc.id))
    await db.commit()

    for doc_id in claimed_ids:
        continue_processing.delay(doc_id)

    return {"queued": len(claimed_ids), "skipped": skipped + len(reprocessable) - len(claimed_ids)}


@router.get("/{collection_id}/export")
async def export_collection(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """RAG data export: collection settings + every document's chunks/metadata
    as a downloadable JSON. Vectors are intentionally excluded — they are
    reproducible by re-embedding the text with the recorded model."""
    from app.services.qdrant_service import qdrant_service

    collection = await db.scalar(select(Collection).where(Collection.id == collection_id))
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    await check_collection_access(db, collection_id, current_user, min_role="viewer")

    docs = (
        await db.scalars(select(Document).where(Document.collection_id == collection_id))
    ).all()

    exported_docs = []
    for doc in docs:
        hits = qdrant_service.scroll_by_document(str(doc.id))
        hits.sort(key=lambda h: h["payload"].get("chunk_index", 0))
        exported_docs.append(
            {
                "id": str(doc.id),
                "filename": doc.original_filename,
                "status": doc.status,
                "tags": doc.tags or [],
                "summary": doc.summary,
                "chunks": [
                    {
                        "chunk_index": h["payload"].get("chunk_index"),
                        "text": h["payload"].get("text", ""),
                        "page_number": h["payload"].get("page_number"),
                        "disabled": bool(h["payload"].get("disabled", False)),
                    }
                    for h in hits
                ],
            }
        )

    payload = {
        "collection": {
            "id": str(collection.id),
            "name": collection.name,
            "description": collection.description,
            "embedding_model": collection.embedding_model,
            "chunk_max_tokens": collection.chunk_max_tokens,
            "chunk_min_tokens": collection.chunk_min_tokens,
            "chunk_overlap_tokens": collection.chunk_overlap_tokens,
            "exported_at": datetime.utcnow().isoformat(),
        },
        "documents": exported_docs,
    }
    import json

    from fastapi.responses import Response

    filename = f"collection-{collection.id}-export.json"
    # Pretty-printed + non-escaped Korean so the exported file is directly
    # readable in an editor, not a single compact line.
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{collection_id}/invite")
async def invite_member(
    collection_id: UUID,
    data: MemberInvite,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    collection = await db.scalar(select(Collection).where(Collection.id == collection_id))
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    if str(collection.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    invitee = await db.scalar(select(User).where(User.email == data.email))
    if not invitee:
        raise HTTPException(status_code=404, detail="가입된 사용자만 초대할 수 있습니다")
    if str(invitee.id) == str(current_user.id):
        raise HTTPException(status_code=400, detail="자기 자신은 초대할 수 없습니다")

    membership = await db.scalar(
        select(CollectionMember).where(
            CollectionMember.collection_id == collection_id,
            CollectionMember.user_id == str(invitee.id),
        )
    )
    if membership:
        membership.role = data.role
    else:
        db.add(CollectionMember(
            collection_id=str(collection_id),
            user_id=str(invitee.id),
            role=data.role,
            invited_by=str(current_user.id),
        ))
    await db.commit()
    return {"message": "초대되었습니다", "email": invitee.email, "role": data.role}


@router.get("/{collection_id}/members")
async def list_members(
    collection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    collection = await check_collection_access(db, collection_id, current_user, min_role="viewer")

    owner = await db.scalar(select(User).where(User.id == collection.created_by))
    rows = (
        await db.execute(
            select(CollectionMember, User)
            .join(User, User.id == CollectionMember.user_id)
            .where(CollectionMember.collection_id == collection_id)
        )
    ).all()

    members = []
    if owner:
        members.append({
            "user_id": owner.id, "email": owner.email, "username": owner.username,
            "role": "owner", "created_at": collection.created_at,
        })
    for member, user in rows:
        members.append({
            "user_id": user.id, "email": user.email, "username": user.username,
            "role": member.role, "created_at": member.created_at,
        })
    return {"items": members}


@router.delete("/{collection_id}/members/{user_id}")
async def remove_member(
    collection_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    collection = await db.scalar(select(Collection).where(Collection.id == collection_id))
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    if str(collection.created_by) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    if str(user_id) == str(collection.created_by):
        raise HTTPException(status_code=400, detail="소유자는 제거할 수 없습니다")

    await db.execute(
        delete(CollectionMember).where(
            CollectionMember.collection_id == collection_id,
            CollectionMember.user_id == str(user_id),
        )
    )
    await db.commit()
    return {"message": "멤버가 제거되었습니다"}
