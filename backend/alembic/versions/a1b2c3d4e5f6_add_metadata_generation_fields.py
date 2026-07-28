"""add metadata generation fields (document/element/chunk)

Revision ID: a1b2c3d4e5f6
Revises: f6a8c0d2e4f6
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f6a8c0d2e4f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 메타 정보 생성 설계서(2026-07-23) — Document 레벨: title/language/category/
    # page_count는 문서 내용에서 자동 생성(Phase 1), author/organization/
    # security_level/source_system은 자동 생성 불가라 사용자가 채워 넣는 전용
    # 필드(Phase 2, PATCH /documents/{id}/metadata). 전부 nullable — 기존 문서는
    # NULL로 남고 재처리/사용자 입력 시에만 채워진다.
    op.add_column("documents", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("language", sa.String(10), nullable=True))
    op.add_column("documents", sa.Column("category", sa.String(50), nullable=True))
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("author", sa.String(255), nullable=True))
    op.add_column("documents", sa.Column("organization", sa.String(255), nullable=True))
    op.add_column("documents", sa.Column("security_level", sa.String(20), nullable=True))
    op.add_column("documents", sa.Column("source_system", sa.String(100), nullable=True))

    # document_nodes: 노드가 만들어진 출처 Docling element id를 보존해, chunk가
    # 어느 element에서 파생됐는지(Phase 4) 역추적할 수 있게 한다. Legacy 엔진/
    # HWP·HWPX 문서는 항상 NULL.
    op.add_column("document_nodes", sa.Column("element_id", sa.Text(), nullable=True))

    # document_chunks: chunk_type/keywords/embedding_model은 신규, element_id는
    # 위 document_nodes.element_id를 chunk까지 전파하기 위한 연결 컬럼.
    op.add_column("document_chunks", sa.Column("chunk_type", sa.String(20), nullable=True))
    op.add_column("document_chunks", sa.Column("keywords", sa.JSON(), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding_model", sa.String(100), nullable=True))
    op.add_column("document_chunks", sa.Column("element_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "element_id")
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "keywords")
    op.drop_column("document_chunks", "chunk_type")

    op.drop_column("document_nodes", "element_id")

    op.drop_column("documents", "source_system")
    op.drop_column("documents", "security_level")
    op.drop_column("documents", "organization")
    op.drop_column("documents", "author")
    op.drop_column("documents", "page_count")
    op.drop_column("documents", "category")
    op.drop_column("documents", "language")
    op.drop_column("documents", "title")
