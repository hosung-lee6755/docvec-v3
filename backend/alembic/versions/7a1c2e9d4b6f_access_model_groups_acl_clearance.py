"""v3 access model: user groups, document ACL, user clearance, collection default level

Revision ID: 7a1c2e9d4b6f
Revises: 4d6f8a0c2e4b
Create Date: 2026-11-10 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7a1c2e9d4b6f"
down_revision: Union[str, None] = "4d6f8a0c2e4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 기존 사용자는 모두 Internal 열람등급으로 시작한다(server_default). 기존 문서는
    # security_level 이 NULL 이고 컬렉션 기본값도 NULL 이라 Public 으로 판정되므로,
    # 마이그레이션 직후 누구에게도 보이던 문서가 사라지지 않는다.
    op.add_column(
        "users",
        sa.Column("clearance_level", sa.String(20), nullable=False, server_default="Internal"),
    )
    op.add_column(
        "collections", sa.Column("default_security_level", sa.String(20), nullable=True)
    )

    op.create_table(
        "user_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_user_groups_name", "user_groups", ["name"], unique=True)

    op.create_table(
        "user_group_members",
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "added_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_user_group_members_user_id", "user_group_members", ["user_id"])

    op.create_table(
        "document_acl_entries",
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("principal_type", sa.String(10), primary_key=True),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "principal_type IN ('user', 'group')", name="ck_document_acl_principal_type"
        ),
    )
    op.create_index(
        "ix_document_acl_principal", "document_acl_entries", ["principal_type", "principal_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_document_acl_principal", table_name="document_acl_entries")
    op.drop_table("document_acl_entries")
    op.drop_index("ix_user_group_members_user_id", table_name="user_group_members")
    op.drop_table("user_group_members")
    op.drop_index("ix_user_groups_name", table_name="user_groups")
    op.drop_table("user_groups")
    op.drop_column("collections", "default_security_level")
    op.drop_column("users", "clearance_level")
