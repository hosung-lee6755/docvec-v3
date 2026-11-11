"""v3 directory accounts (LDAP/AD) and SMB source connectors

Revision ID: 9c4e6a8b1d2f
Revises: 8b2d4f6a1c3e
Create Date: 2026-11-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9c4e6a8b1d2f"
down_revision: Union[str, None] = "8b2d4f6a1c3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def _external_columns(table: str, source_column: str) -> None:
    op.add_column(table, sa.Column(source_column, sa.String(10), nullable=False, server_default="local"))
    op.add_column(table, sa.Column("external_id", sa.String(184), nullable=True))
    op.add_column(table, sa.Column("external_dn", sa.String(1024), nullable=True))
    op.create_unique_constraint(f"uq_{table}_external_id", table, ["external_id"])


def upgrade() -> None:
    _external_columns("users", "auth_source")
    _external_columns("user_groups", "source")

    op.create_table(
        "source_connectors",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="smb"),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="445"),
        sa.Column("share", sa.String(255), nullable=False),
        sa.Column("base_path", sa.String(1024), nullable=False, server_default=""),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("service_account_sid", sa.String(184), nullable=True),
        sa.Column("collection_id", UUID, sa.ForeignKey("collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("level_rules", sa.JSON(), nullable=True),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_new_per_run", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_source_connectors_collection_id", "source_connectors", ["collection_id"])

    op.create_table(
        "source_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "connector_id", UUID, sa.ForeignKey("source_connectors.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("path", sa.String(2048), nullable=False),
        sa.Column("document_id", UUID, sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("mtime", sa.Float(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("sd_hash", sa.String(64), nullable=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="synced"),
        sa.Column("hold_reason", sa.String(255), nullable=True),
        sa.Column("hold_detail", sa.JSON(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connector_id", "path", name="uq_source_items_connector_path"),
    )
    op.create_index("ix_source_items_connector_id", "source_items", ["connector_id"])
    op.create_index("ix_source_items_document_id", "source_items", ["document_id"])

    op.create_table(
        "connector_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "connector_id", UUID, sa.ForeignKey("source_connectors.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("counts", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("triggered_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_connector_runs_connector_id", "connector_runs", ["connector_id"])
    op.create_index("ix_connector_runs_started_at", "connector_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_connector_runs_started_at", table_name="connector_runs")
    op.drop_index("ix_connector_runs_connector_id", table_name="connector_runs")
    op.drop_table("connector_runs")
    op.drop_index("ix_source_items_document_id", table_name="source_items")
    op.drop_index("ix_source_items_connector_id", table_name="source_items")
    op.drop_table("source_items")
    op.drop_index("ix_source_connectors_collection_id", table_name="source_connectors")
    op.drop_table("source_connectors")
    for table, source_column in (("user_groups", "source"), ("users", "auth_source")):
        op.drop_constraint(f"uq_{table}_external_id", table, type_="unique")
        op.drop_column(table, "external_dn")
        op.drop_column(table, "external_id")
        op.drop_column(table, source_column)
