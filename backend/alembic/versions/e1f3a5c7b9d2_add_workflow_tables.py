"""add workflow tables

Revision ID: e1f3a5c7b9d2
Revises: a374336382c7
Create Date: 2026-07-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f3a5c7b9d2'
down_revision: Union[str, None] = 'a374336382c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('workflow_definitions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('DRAFT', 'ACTIVE', 'INACTIVE', name='workflow_status'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_definitions_project_id'), 'workflow_definitions', ['project_id'], unique=False)
    op.create_index(op.f('ix_workflow_definitions_status'), 'workflow_definitions', ['status'], unique=False)

    op.create_table('workflow_versions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workflow_id', sa.UUID(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('published_at', sa.DateTime(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflow_definitions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_versions_workflow_id'), 'workflow_versions', ['workflow_id'], unique=False)

    op.create_table('workflow_block_instances',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('block_type', sa.String(length=50), nullable=False),
    sa.Column('label', sa.String(length=255), nullable=True),
    sa.Column('position', sa.JSON(), nullable=False),
    sa.Column('config', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['version_id'], ['workflow_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_block_instances_version_id'), 'workflow_block_instances', ['version_id'], unique=False)

    op.create_table('workflow_edges',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('from_block_id', sa.UUID(), nullable=False),
    sa.Column('to_block_id', sa.UUID(), nullable=False),
    sa.Column('condition', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['from_block_id'], ['workflow_block_instances.id'], ),
    sa.ForeignKeyConstraint(['to_block_id'], ['workflow_block_instances.id'], ),
    sa.ForeignKeyConstraint(['version_id'], ['workflow_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_edges_version_id'), 'workflow_edges', ['version_id'], unique=False)

    op.create_table('workflow_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=True),
    sa.Column('collection_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Enum('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED', name='workflow_run_status'), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['version_id'], ['workflow_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_runs_version_id'), 'workflow_runs', ['version_id'], unique=False)
    op.create_index(op.f('ix_workflow_runs_status'), 'workflow_runs', ['status'], unique=False)

    op.create_table('workflow_run_steps',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('block_instance_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', name='workflow_run_step_status'), nullable=False),
    sa.Column('completed_incoming_edges', sa.Integer(), nullable=False),
    sa.Column('input', sa.JSON(), nullable=True),
    sa.Column('output', sa.JSON(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['block_instance_id'], ['workflow_block_instances.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['workflow_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_run_steps_run_id'), 'workflow_run_steps', ['run_id'], unique=False)
    op.create_index(op.f('ix_workflow_run_steps_status'), 'workflow_run_steps', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_workflow_run_steps_status'), table_name='workflow_run_steps')
    op.drop_index(op.f('ix_workflow_run_steps_run_id'), table_name='workflow_run_steps')
    op.drop_table('workflow_run_steps')
    op.drop_index(op.f('ix_workflow_runs_status'), table_name='workflow_runs')
    op.drop_index(op.f('ix_workflow_runs_version_id'), table_name='workflow_runs')
    op.drop_table('workflow_runs')
    op.drop_index(op.f('ix_workflow_edges_version_id'), table_name='workflow_edges')
    op.drop_table('workflow_edges')
    op.drop_index(op.f('ix_workflow_block_instances_version_id'), table_name='workflow_block_instances')
    op.drop_table('workflow_block_instances')
    op.drop_index(op.f('ix_workflow_versions_workflow_id'), table_name='workflow_versions')
    op.drop_table('workflow_versions')
    op.drop_index(op.f('ix_workflow_definitions_status'), table_name='workflow_definitions')
    op.drop_index(op.f('ix_workflow_definitions_project_id'), table_name='workflow_definitions')
    op.drop_table('workflow_definitions')
    sa.Enum(name='workflow_run_step_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='workflow_run_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='workflow_status').drop(op.get_bind(), checkfirst=True)
