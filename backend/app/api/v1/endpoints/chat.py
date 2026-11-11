import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.api.v1.permissions import check_collection_access, check_project_access
from app.db.models.chat_conversation import ChatConversation
from app.db.models.chat_message import ChatMessage
from app.db.models.project_api_key import ProjectApiKey
from app.db.models.user import User
from app.db.models.user_api_key import UserApiKey
from app.db.session import get_db
from app.services.access_policy import build_access_context, load_document_facts, visible_document_ids
from app.services.llm import LLM_MODEL_REGISTRY

router = APIRouter()

_TITLE_MAX_LEN = 60


def _derive_title(query: str) -> str:
    trimmed = query.strip().replace("\n", " ")
    return trimmed[:_TITLE_MAX_LEN] + ("..." if len(trimmed) > _TITLE_MAX_LEN else "")


class ChatCitation(BaseModel):
    index: int
    document_id: str | None
    collection_id: str | None = None
    collection_name: str | None = None
    filename: str | None
    page_number: int | None
    text: str
    # v3: 지금 볼 수 없는 문서의 인용이면 True다. 본문·파일명·문서 id를 비워서 내려보낸다.
    hidden: bool = False


class ChatMessageResponse(BaseModel):
    id: UUID
    status: str
    query: str
    answer: str | None
    citations: list[ChatCitation] | None
    error_message: str | None
    created_at: datetime
    # Streaming: partial text mirrored to Redis by the worker while the answer
    # is still GENERATING — see generate_answer's _write_partial.
    partial_answer: str | None = None
    # v3 마일스톤 5 심층 검색: 모드, 끝난 뒤의 검색 과정, 생성 중의 진행 단계
    mode: str = "standard"
    agent_steps: dict | None = None
    progress: dict | None = None

    class Config:
        from_attributes = True


_partial_redis = None


def _redis_value(key: str) -> str | None:
    global _partial_redis
    try:
        if _partial_redis is None:
            import redis

            from app.core.config import settings as _settings

            _partial_redis = redis.from_url(_settings.redis_url)
        val = _partial_redis.get(key)
        return val.decode("utf-8") if val else None
    except Exception:
        return None


def _partial_answer_for(message_id) -> str | None:
    return _redis_value(f"chat_partial:{message_id}")


def _progress_for(message_id) -> dict | None:
    raw = _redis_value(f"chat_progress:{message_id}")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _as_uuid(value: str | None) -> str | None:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _masked(citation: ChatCitation) -> ChatCitation:
    return citation.model_copy(update={
        "hidden": True, "document_id": None, "collection_id": None, "collection_name": None,
        "filename": None, "page_number": None, "text": "",
    })


async def _mask_hidden_citations(
    db: AsyncSession, user: User, messages: list[ChatMessageResponse]
) -> list[ChatMessageResponse]:
    """저장된 답변의 인용과 심층 검색 기록을 지금 권한으로 다시 판정한다. 권한이 회수됐거나 문서가
    지워졌으면 가린다. 답변 본문은 이미 보여 준 것이므로 그대로 둔다(v3 마일스톤 2, 5)."""
    from app.services.agentic.deep_search import mask_step_documents, step_document_ids

    if not any(m.citations or step_document_ids(m.agent_steps) for m in messages):
        return messages
    doc_ids = {_as_uuid(c.document_id) for m in messages for c in (m.citations or [])}
    for m in messages:
        doc_ids |= step_document_ids(m.agent_steps)
    doc_ids -= {None}
    visible: set[str] = set()
    if doc_ids:
        ctx = await build_access_context(db, user)
        visible = visible_document_ids(ctx, await load_document_facts(db, doc_ids))

    def check(c: ChatCitation) -> ChatCitation:
        # 문서를 특정할 수 없는 인용은 판정할 수 없으므로 가린다(fail-closed).
        return c if _as_uuid(c.document_id) in visible else _masked(c)

    return [
        m.model_copy(update={
            "citations": [check(c) for c in m.citations] if m.citations else m.citations,
            "agent_steps": mask_step_documents(m.agent_steps, visible),
        })
        for m in messages
    ]


def _message_with_partial(message: "ChatMessage") -> ChatMessageResponse:
    item = ChatMessageResponse.model_validate(message)
    if item.status == "GENERATING":
        item.partial_answer = _partial_answer_for(message.id)
        if item.mode == "deep":
            item.progress = _progress_for(message.id)
    return item


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    model_key: str
    project_id: UUID | None
    collection_id: UUID | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationDetailResponse(ConversationResponse):
    messages: list[ChatMessageResponse]


class CreateConversationRequest(BaseModel):
    query: str
    project_id: UUID | None = None
    collection_id: UUID | None = None
    model_key: str
    mode: Literal["standard", "deep"] = "standard"


class CreateMessageRequest(BaseModel):
    query: str
    mode: Literal["standard", "deep"] = "standard"


class RenameConversationRequest(BaseModel):
    title: str


async def _validate_model_and_key(
    db: AsyncSession, current_user: User, model_key: str, project_id: UUID | None = None
) -> None:
    if model_key not in LLM_MODEL_REGISTRY:
        raise HTTPException(status_code=422, detail="알 수 없는 모델입니다")
    spec = LLM_MODEL_REGISTRY[model_key]
    if spec["backend"] in ("openai", "anthropic"):
        # A project-scoped key (registered in that project's AI 관리 settings) takes
        # priority so project members can chat without each registering their own key.
        has_project_key = False
        if project_id:
            has_project_key = bool(
                await db.scalar(
                    select(ProjectApiKey.id).where(
                        ProjectApiKey.project_id == str(project_id),
                        ProjectApiKey.provider == spec["backend"],
                    )
                )
            )
        if not has_project_key:
            has_key = await db.scalar(
                select(UserApiKey.id).where(
                    UserApiKey.user_id == str(current_user.id),
                    UserApiKey.provider == spec["backend"],
                )
            )
            if not has_key:
                raise HTTPException(
                    status_code=422,
                    detail=f"{spec['backend']} API 키를 먼저 프로젝트 설정 또는 개인 설정에서 등록해주세요",
                )


async def _get_owned_conversation(
    db: AsyncSession, conversation_id: UUID, current_user: User
) -> ChatConversation:
    conversation = await db.scalar(
        select(ChatConversation).where(ChatConversation.id == conversation_id)
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if str(conversation.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return conversation


@router.get("/chat/models")
async def list_chat_models(
    project_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.pipeline.tasks.chat import _SYSTEM_PROMPT

    registered = set(
        (
            await db.scalars(
                select(UserApiKey.provider).where(UserApiKey.user_id == str(current_user.id))
            )
        ).all()
    )
    if project_id:
        await check_project_access(db, project_id, current_user, min_role="viewer")
        registered |= set(
            (
                await db.scalars(
                    select(ProjectApiKey.provider).where(ProjectApiKey.project_id == str(project_id))
                )
            ).all()
        )
    return {
        "default_system_prompt": _SYSTEM_PROMPT,
        "items": [
            {
                "key": key,
                "label": spec["label"],
                "backend": spec["backend"],
                # Local models are always usable; cloud models require the user to
                # have already registered that provider's API key.
                "available": spec["backend"] == "local" or spec["backend"] in registered,
            }
            for key, spec in LLM_MODEL_REGISTRY.items()
        ]
    }


# 질문 1건마다 LLM 생성 태스크가 하나 돈다. 심층 검색은 검색 최대 7회와 LLM 3회를 쓰므로 따로 더 좁게 막는다.
_CHAT_MESSAGES_PER_MINUTE = 30
_DEEP_MESSAGES_PER_MINUTE = 5


def _enforce_chat_rate_limit(user: User, mode: str) -> None:
    from app.core.rate_limit import enforce_user_rate_limit

    enforce_user_rate_limit(str(user.id), "chat_message", limit=_CHAT_MESSAGES_PER_MINUTE, window_seconds=60)
    if mode == "deep":
        enforce_user_rate_limit(str(user.id), "chat_deep", limit=_DEEP_MESSAGES_PER_MINUTE, window_seconds=60)


@router.post("/chat/conversations", response_model=ConversationDetailResponse)
async def create_conversation(
    data: CreateConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.pipeline.tasks.chat import generate_answer

    _enforce_chat_rate_limit(current_user, data.mode)
    await _validate_model_and_key(db, current_user, data.model_key, project_id=data.project_id)
    if data.project_id:
        await check_project_access(db, data.project_id, current_user, min_role="viewer")
    if data.collection_id:
        await check_collection_access(db, data.collection_id, current_user, min_role="viewer")

    conversation = ChatConversation(
        user_id=str(current_user.id),
        project_id=str(data.project_id) if data.project_id else None,
        collection_id=str(data.collection_id) if data.collection_id else None,
        model_key=data.model_key,
        title=_derive_title(data.query),
    )
    db.add(conversation)
    await db.flush()

    msg = ChatMessage(conversation_id=conversation.id, query=data.query, status="PENDING", mode=data.mode)
    db.add(msg)
    await db.commit()
    await db.refresh(conversation)
    await db.refresh(msg)

    generate_answer.delay(str(msg.id))

    return ConversationDetailResponse(
        **ConversationResponse.model_validate(conversation).model_dump(),
        messages=[ChatMessageResponse.model_validate(msg)],
    )


@router.get("/chat/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    project_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if project_id is not None:
        await check_project_access(db, project_id, current_user, min_role="viewer")

    # 외부 에이전트(MCP)의 ask 대화는 웹 채팅 목록에 넣지 않는다(답변 추적 기록에서 본다)
    filters = [ChatConversation.user_id == str(current_user.id), ChatConversation.channel == "web"]
    # Personal ("전체" 채팅 메뉴) and project-scoped chat history are kept separate:
    # omit project_id to see only personal conversations, pass it to see only that
    # project's — never a mix of both.
    filters.append(
        ChatConversation.project_id == str(project_id)
        if project_id is not None
        else ChatConversation.project_id.is_(None)
    )
    rows = await db.scalars(
        select(ChatConversation).where(*filters).order_by(ChatConversation.updated_at.desc())
    )
    return rows.all()


@router.get("/chat/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user)
    messages = await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation.id)
        .order_by(ChatMessage.created_at)
    )
    return ConversationDetailResponse(
        **ConversationResponse.model_validate(conversation).model_dump(),
        messages=await _mask_hidden_citations(
            db, current_user, [_message_with_partial(m) for m in messages.all()]
        ),
    )


@router.patch("/chat/conversations/{conversation_id}", response_model=ConversationResponse)
async def rename_conversation(
    conversation_id: UUID,
    data: RenameConversationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user)
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="제목을 입력해주세요")
    conversation.title = title[:_TITLE_MAX_LEN]
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.delete("/chat/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await _get_owned_conversation(db, conversation_id, current_user)
    await db.execute(
        ChatMessage.__table__.delete().where(ChatMessage.conversation_id == conversation.id)
    )
    await db.delete(conversation)
    await db.commit()


@router.post(
    "/chat/conversations/{conversation_id}/messages", response_model=ChatMessageResponse
)
async def create_message(
    conversation_id: UUID,
    data: CreateMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.pipeline.tasks.chat import generate_answer

    _enforce_chat_rate_limit(current_user, data.mode)
    conversation = await _get_owned_conversation(db, conversation_id, current_user)

    msg = ChatMessage(conversation_id=conversation.id, query=data.query, status="PENDING", mode=data.mode)
    db.add(msg)
    conversation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(msg)

    generate_answer.delay(str(msg.id))

    return msg


@router.get("/chat/{chat_message_id}", response_model=ChatMessageResponse)
async def get_chat_message(
    chat_message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msg = await db.scalar(select(ChatMessage).where(ChatMessage.id == chat_message_id))
    if not msg:
        raise HTTPException(status_code=404, detail="Chat message not found")
    conversation = await db.scalar(
        select(ChatConversation).where(ChatConversation.id == msg.conversation_id)
    )
    if not conversation or str(conversation.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    [item] = await _mask_hidden_citations(db, current_user, [_message_with_partial(msg)])
    return item
