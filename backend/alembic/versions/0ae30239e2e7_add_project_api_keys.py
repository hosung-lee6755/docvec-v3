"""add project_api_keys

Revision ID: 0ae30239e2e7
Revises: 62e8aaf9b0cf
Create Date: 2026-07-06 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ae30239e2e7'
down_revision: Union[str, None] = '62e8aaf9b0cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Raw SQL, not op.create_table with a sa.Enum column: SQLAlchemy's Enum DDL
    # (even with create_type=False) reliably re-attempts CREATE TYPE against the
    # api_key_provider type already created by the user_api_keys migration
    # (08c99a888ee0), which errors since it exists. Referencing the existing
    # type by name directly in raw SQL sidesteps that entirely.
    op.execute("""
        CREATE TABLE project_api_keys (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id),
            provider api_key_provider NOT NULL,
            encrypted_key TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            CONSTRAINT uq_project_api_keys_project_provider UNIQUE (project_id, provider)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE project_api_keys")
