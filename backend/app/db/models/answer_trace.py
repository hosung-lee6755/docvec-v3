"""답변 추적 기록(v3 마일스톤 2, 거버넌스·감사 증적).

채팅 답변 한 건마다 누가 물었는지, 어떤 권한으로 판정했는지, 어떤 청크를 근거로 넣었고
어떤 모델이 만들었는지를 남긴다. 대화·메시지·사용자를 지워도 기록은 남는다(FK SET NULL).

청크 본문은 복사하지 않는다. 문서 id, 그때의 파일명·유효 등급, 점수, 본문 해시만 둔다.
본문 사본이 권한 밖으로 새는 경로를 만들지 않기 위해서이며, 조회 화면은 보는 사람의
현재 열람 권한으로 원본을 다시 판정해 보여 준다.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

GROUNDING_PASSED = "passed"
GROUNDING_FAILED = "failed"
GROUNDING_SKIPPED = "skipped"


class AnswerTrace(Base):
    __tablename__ = "answer_traces"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    chat_message_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # 대화는 지워질 수 있으므로 FK 없이 id만 보관한다.
    conversation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_role: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # 판정에 쓴 권한 맥락(스냅샷)
    clearance_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    group_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    accessible_collection_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    access_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope_collection_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    scope_project_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # 검색과 생성
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    broadened: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    grounding: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verifier_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_prompt_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    system_prompt_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 답변이 어느 통로로 나갔는지(web, mcp)와 MCP라면 어떤 개인 접근 토큰이었는지. 토큰은 지워져도 id를 남긴다.
    channel: Mapped[str] = mapped_column(String(10), default="web", server_default="web", nullable=False)
    access_token_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # 심층 검색(v3 마일스톤 5)이면 deep. agent_steps에는 하위 질문, 검색 횟수, 찾은 문서 id와 파일명만 둔다(본문 없음)
    mode: Mapped[str] = mapped_column(String(10), default="standard", server_default="standard", nullable=False)
    agent_steps: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 결과
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class AnswerTraceSource(Base):
    """LLM에 근거로 넣은 청크 한 건. rank는 프롬프트의 발췌문 번호([n])와 같다."""

    __tablename__ = "answer_trace_sources"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    trace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_traces.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    # 문서가 지워져도 기록은 남아야 하므로 FK 없이 문자열로 보관한다.
    document_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    collection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    security_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    chunk_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
