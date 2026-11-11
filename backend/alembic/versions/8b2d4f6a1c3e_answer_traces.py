"""v3 governance: answer traces and search result document ids

Revision ID: 8b2d4f6a1c3e
Revises: 7a1c2e9d4b6f
Create Date: 2026-11-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8b2d4f6a1c3e"
down_revision: Union[str, None] = "7a1c2e9d4b6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "answer_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chat_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("user_role", sa.String(20), nullable=True),
        sa.Column("clearance_level", sa.String(20), nullable=True),
        sa.Column("group_ids", sa.JSON(), nullable=True),
        sa.Column("accessible_collection_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("access_fingerprint", sa.String(64), nullable=True),
        sa.Column("scope_collection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope_project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("intent", sa.String(32), nullable=True),
        sa.Column("broadened", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("grounding", sa.String(16), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model_key", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("verifier_model", sa.String(64), nullable=True),
        sa.Column("system_prompt_source", sa.String(16), nullable=True),
        sa.Column("system_prompt_sha256", sa.String(64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_answer_traces_chat_message_id", "answer_traces", ["chat_message_id"])
    op.create_index("ix_answer_traces_user_id", "answer_traces", ["user_id"])
    op.create_index("ix_answer_traces_created_at", "answer_traces", ["created_at"])

    op.create_table(
        "answer_trace_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("answer_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=True),
        sa.Column("collection_id", sa.String(64), nullable=True),
        sa.Column("filename", sa.String(512), nullable=True),
        sa.Column("security_level", sa.String(20), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("chunk_ref", sa.String(64), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("cited", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_answer_trace_sources_trace_id", "answer_trace_sources", ["trace_id"])
    op.create_index("ix_answer_trace_sources_document_id", "answer_trace_sources", ["document_id"])

    op.add_column("search_history", sa.Column("result_document_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("search_history", "result_document_ids")
    op.drop_index("ix_answer_trace_sources_document_id", table_name="answer_trace_sources")
    op.drop_index("ix_answer_trace_sources_trace_id", table_name="answer_trace_sources")
    op.drop_table("answer_trace_sources")
    op.drop_index("ix_answer_traces_created_at", table_name="answer_traces")
    op.drop_index("ix_answer_traces_user_id", table_name="answer_traces")
    op.drop_index("ix_answer_traces_chat_message_id", table_name="answer_traces")
    op.drop_table("answer_traces")
