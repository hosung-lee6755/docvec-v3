"""scope collection qdrant_collection_name uniqueness per owner

Revision ID: 313b3f79856a
Revises: 7c0a8247f3e8
Create Date: 2026-07-03 07:49:05.385039

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '313b3f79856a'
down_revision: Union[str, None] = '7c0a8247f3e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "collections_qdrant_collection_name_key", "collections", type_="unique"
    )
    op.create_unique_constraint(
        "uq_collection_owner_qdrant_name",
        "collections",
        ["created_by", "qdrant_collection_name"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_collection_owner_qdrant_name", "collections", type_="unique"
    )
    op.create_unique_constraint(
        "collections_qdrant_collection_name_key", "collections", ["qdrant_collection_name"]
    )
