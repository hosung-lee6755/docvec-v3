"""add preprocessing workflow data model

Revision ID: b7e3f9a1c5d8
Revises: e1f3a5c7b9d2
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7e3f9a1c5d8'
down_revision: Union[str, None] = 'e1f3a5c7b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- document_nodes ---------------------------------------------------
    op.create_table(
        'document_nodes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('node_type', sa.Enum(
            'DOCUMENT', 'COVER', 'TOC', 'SECTION', 'HEADING', 'PARAGRAPH', 'SENTENCE',
            'LIST', 'LIST_ITEM', 'TABLE', 'TABLE_ROW', 'TABLE_CELL', 'IMAGE', 'CAPTION',
            'FOOTNOTE', 'HEADER', 'FOOTER', 'PAGE_NUMBER', 'FORM_FIELD',
            name='document_node_type',
        ), nullable=False),
        sa.Column('level', sa.Integer(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('parent_node_id', sa.UUID(), nullable=True),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('span_start', sa.Integer(), nullable=True),
        sa.Column('span_end', sa.Integer(), nullable=True),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('style', sa.JSON(), nullable=True),
        sa.Column('user_corrected', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['workflow_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_node_id'], ['document_nodes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_document_nodes_document_id'), 'document_nodes', ['document_id'])
    op.create_index(op.f('ix_document_nodes_run_id'), 'document_nodes', ['run_id'])

    # --- cleaning_rules -----------------------------------------------------
    op.create_table(
        'cleaning_rules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('rule_name', sa.String(length=255), nullable=False),
        sa.Column('rule_type', sa.Enum(
            'REGEX_REPLACE', 'EXACT_REMOVE', 'LINE_FILTER', 'BUILTIN', name='cleaning_rule_type',
        ), nullable=False),
        sa.Column('pattern', sa.Text(), nullable=True),
        sa.Column('replacement', sa.Text(), nullable=True),
        sa.Column('scope', sa.Enum(
            'DOCUMENT', 'PARAGRAPH', 'LINE', name='cleaning_rule_scope',
        ), nullable=False, server_default='PARAGRAPH'),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- document_chunks ------------------------------------------------------
    op.create_table(
        'document_chunks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('chunk_order', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('original_text', sa.Text(), nullable=True),
        sa.Column('token_count', sa.Integer(), nullable=True),
        sa.Column('page_start', sa.Integer(), nullable=True),
        sa.Column('page_end', sa.Integer(), nullable=True),
        sa.Column('section_path', sa.JSON(), nullable=True),
        sa.Column('source_node_ids', sa.JSON(), nullable=True),
        sa.Column('prev_chunk_id', sa.UUID(), nullable=True),
        sa.Column('next_chunk_id', sa.UUID(), nullable=True),
        sa.Column('span_start', sa.Integer(), nullable=True),
        sa.Column('span_end', sa.Integer(), nullable=True),
        sa.Column('embedded', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('edited', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('excluded_pii', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('workflow_version', sa.Integer(), nullable=True),
        sa.Column('dictionary_version', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['workflow_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['prev_chunk_id'], ['document_chunks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['next_chunk_id'], ['document_chunks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_document_chunks_document_id'), 'document_chunks', ['document_id'])
    op.create_index(op.f('ix_document_chunks_run_id'), 'document_chunks', ['run_id'])

    # --- cleaning_changes -----------------------------------------------------
    op.create_table(
        'cleaning_changes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('step_id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('rule_id', sa.UUID(), nullable=True),
        sa.Column('rule_key', sa.String(length=100), nullable=True),
        sa.Column('node_id', sa.UUID(), nullable=True),
        sa.Column('before_sample', sa.Text(), nullable=True),
        sa.Column('after_sample', sa.Text(), nullable=True),
        sa.Column('change_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['workflow_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['step_id'], ['workflow_run_steps.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rule_id'], ['cleaning_rules.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['node_id'], ['document_nodes.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_cleaning_changes_run_id'), 'cleaning_changes', ['run_id'])
    op.create_index(op.f('ix_cleaning_changes_step_id'), 'cleaning_changes', ['step_id'])
    op.create_index(op.f('ix_cleaning_changes_document_id'), 'cleaning_changes', ['document_id'])

    # --- dictionary_applications -----------------------------------------------
    op.create_table(
        'dictionary_applications',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('step_id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('dictionary_type', sa.Enum(
            'STOPWORD', 'SYNONYM', 'USER_DICT', name='dictionary_application_type',
        ), nullable=False),
        sa.Column('entry_id', sa.UUID(), nullable=True),
        sa.Column('dictionary_version', sa.Integer(), nullable=False),
        sa.Column('original_text', sa.Text(), nullable=False),
        sa.Column('normalized_text', sa.Text(), nullable=True),
        sa.Column('node_id', sa.UUID(), nullable=True),
        sa.Column('chunk_id', sa.UUID(), nullable=True),
        sa.Column('start_offset', sa.Integer(), nullable=True),
        sa.Column('end_offset', sa.Integer(), nullable=True),
        sa.Column('reverted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['workflow_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['step_id'], ['workflow_run_steps.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entry_id'], ['dictionary_entries.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['node_id'], ['document_nodes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['chunk_id'], ['document_chunks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_dictionary_applications_run_id'), 'dictionary_applications', ['run_id'])
    op.create_index(op.f('ix_dictionary_applications_step_id'), 'dictionary_applications', ['step_id'])
    op.create_index(op.f('ix_dictionary_applications_document_id'), 'dictionary_applications', ['document_id'])

    # --- pii_detections -------------------------------------------------------
    op.create_table(
        'pii_detections',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('action', sa.Enum(
            'MARK', 'MASK', 'TOKENIZE', 'REMOVE', 'EXCLUDE_EMBEDDING', name='pii_action',
        ), nullable=False),
        sa.Column('original_encrypted', sa.Text(), nullable=True),
        sa.Column('masked_value', sa.String(length=255), nullable=True),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('node_id', sa.UUID(), nullable=True),
        sa.Column('start_offset', sa.Integer(), nullable=True),
        sa.Column('end_offset', sa.Integer(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['workflow_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['node_id'], ['document_nodes.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_pii_detections_run_id'), 'pii_detections', ['run_id'])
    op.create_index(op.f('ix_pii_detections_document_id'), 'pii_detections', ['document_id'])

    # --- quality_reports ------------------------------------------------------
    op.create_table(
        'quality_reports',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('overall_score', sa.Float(), nullable=True),
        sa.Column('scores', sa.JSON(), nullable=True),
        sa.Column('metrics', sa.JSON(), nullable=True),
        sa.Column('warnings', sa.JSON(), nullable=True),
        sa.Column('status', sa.Enum(
            'SUCCESS', 'SUCCESS_WITH_WARNING', 'REVIEW_REQUIRED', 'PARTIAL_FAILURE', 'FAILURE',
            name='quality_report_status',
        ), nullable=False),
        sa.Column('reviewed_by', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['workflow_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_quality_reports_run_id'), 'quality_reports', ['run_id'], unique=True)
    op.create_index(op.f('ix_quality_reports_document_id'), 'quality_reports', ['document_id'])

    # --- dictionary_revisions -------------------------------------------------
    op.create_table(
        'dictionary_revisions',
        sa.Column('version', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('changed_entry_id', sa.UUID(), nullable=True),
        sa.Column('change_type', sa.Enum(
            'CREATE', 'UPDATE', 'DELETE', 'IMPORT', name='dictionary_change_type',
        ), nullable=False),
        sa.Column('snapshot_key', sa.String(length=512), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['changed_entry_id'], ['dictionary_entries.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('version'),
    )

    # --- block_execution_cache --------------------------------------------------
    op.create_table(
        'block_execution_cache',
        sa.Column('cache_key', sa.String(length=128), nullable=False),
        sa.Column('artifact_key', sa.String(length=512), nullable=False),
        sa.Column('output_summary', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_hit_at', sa.DateTime(), nullable=True),
        sa.Column('hit_count', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('cache_key'),
    )

    # --- collections: default preprocessing workflow ---------------------------
    op.add_column('collections', sa.Column('default_workflow_id', sa.UUID(), nullable=True))
    op.add_column('collections', sa.Column('default_workflow_version', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_collections_default_workflow_id', 'collections', 'workflow_definitions',
        ['default_workflow_id'], ['id'], ondelete='SET NULL',
    )

    # --- documents: workflow-derived status + quality/version tracking ---------
    op.add_column('documents', sa.Column('active_run_id', sa.UUID(), nullable=True))
    op.add_column('documents', sa.Column('quality_status', sa.String(length=30), nullable=True))
    op.add_column('documents', sa.Column('pipeline_version', sa.JSON(), nullable=True))
    op.create_foreign_key(
        'fk_documents_active_run_id', 'documents', 'workflow_runs',
        ['active_run_id'], ['id'], ondelete='SET NULL',
    )
    for value in ('VALIDATING', 'MASKING', 'WAITING_REVIEW'):
        op.execute(f"ALTER TYPE document_status ADD VALUE IF NOT EXISTS '{value}'")

    # --- workflow_runs: trigger/reprocess lineage/caching context ---------------
    # Unlike op.create_table, op.add_column does not auto-create a native
    # Postgres enum type referenced inline — it must be created explicitly
    # first or the ALTER TABLE ADD COLUMN fails with UndefinedObjectError.
    workflow_run_trigger = sa.Enum(
        'UPLOAD', 'MANUAL', 'REPROCESS', 'COLLECTION_REPROCESS', name='workflow_run_trigger',
    )
    workflow_run_trigger.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'workflow_runs',
        sa.Column(
            'trigger',
            workflow_run_trigger,
            nullable=False,
            server_default='MANUAL',
        ),
    )
    op.add_column('workflow_runs', sa.Column('started_block_id', sa.UUID(), nullable=True))
    op.add_column('workflow_runs', sa.Column('parent_run_id', sa.UUID(), nullable=True))
    op.add_column('workflow_runs', sa.Column('dictionary_version', sa.Integer(), nullable=True))
    op.add_column('workflow_runs', sa.Column('version_snapshot', sa.JSON(), nullable=True))
    op.add_column('workflow_runs', sa.Column('impact', sa.JSON(), nullable=True))
    op.create_foreign_key(
        'fk_workflow_runs_started_block_id', 'workflow_runs', 'workflow_block_instances',
        ['started_block_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_workflow_runs_parent_run_id', 'workflow_runs', 'workflow_runs',
        ['parent_run_id'], ['id'], ondelete='SET NULL',
    )
    op.execute("ALTER TYPE workflow_run_status ADD VALUE IF NOT EXISTS 'WAITING_REVIEW'")

    # --- workflow_run_steps: caching/tracing/error-code columns -----------------
    op.add_column('workflow_run_steps', sa.Column('input_hash', sa.String(length=128), nullable=True))
    op.add_column('workflow_run_steps', sa.Column('output_hash', sa.String(length=128), nullable=True))
    op.add_column('workflow_run_steps', sa.Column('artifact_key', sa.String(length=512), nullable=True))
    op.add_column(
        'workflow_run_steps',
        sa.Column('cached', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column('workflow_run_steps', sa.Column('error_code', sa.String(length=50), nullable=True))
    op.add_column('workflow_run_steps', sa.Column('warnings', sa.JSON(), nullable=True))
    op.add_column('workflow_run_steps', sa.Column('metrics', sa.JSON(), nullable=True))
    op.execute("ALTER TYPE workflow_run_step_status ADD VALUE IF NOT EXISTS 'SKIPPED'")


def downgrade() -> None:
    # workflow_run_steps
    op.drop_column('workflow_run_steps', 'metrics')
    op.drop_column('workflow_run_steps', 'warnings')
    op.drop_column('workflow_run_steps', 'error_code')
    op.drop_column('workflow_run_steps', 'cached')
    op.drop_column('workflow_run_steps', 'artifact_key')
    op.drop_column('workflow_run_steps', 'output_hash')
    op.drop_column('workflow_run_steps', 'input_hash')
    # NOTE: 'SKIPPED' was added to workflow_run_step_status via ALTER TYPE ...
    # ADD VALUE. Postgres cannot drop a single enum value without recreating
    # the type; left in place deliberately (additive, non-destructive) — see
    # 통합 설계서 §13/이 마이그레이션의 계획 문서.

    # workflow_runs
    op.drop_constraint('fk_workflow_runs_parent_run_id', 'workflow_runs', type_='foreignkey')
    op.drop_constraint('fk_workflow_runs_started_block_id', 'workflow_runs', type_='foreignkey')
    op.drop_column('workflow_runs', 'impact')
    op.drop_column('workflow_runs', 'version_snapshot')
    op.drop_column('workflow_runs', 'dictionary_version')
    op.drop_column('workflow_runs', 'parent_run_id')
    op.drop_column('workflow_runs', 'started_block_id')
    op.drop_column('workflow_runs', 'trigger')
    sa.Enum(name='workflow_run_trigger').drop(op.get_bind(), checkfirst=True)
    # NOTE: 'WAITING_REVIEW' added to workflow_run_status left in place — see
    # note above.

    # documents
    op.drop_constraint('fk_documents_active_run_id', 'documents', type_='foreignkey')
    op.drop_column('documents', 'pipeline_version')
    op.drop_column('documents', 'quality_status')
    op.drop_column('documents', 'active_run_id')
    # NOTE: 'VALIDATING'/'MASKING'/'WAITING_REVIEW' added to document_status
    # left in place — see note above.

    # collections
    op.drop_constraint('fk_collections_default_workflow_id', 'collections', type_='foreignkey')
    op.drop_column('collections', 'default_workflow_version')
    op.drop_column('collections', 'default_workflow_id')

    # new tables, reverse dependency order
    op.drop_table('block_execution_cache')
    op.drop_table('dictionary_revisions')
    sa.Enum(name='dictionary_change_type').drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f('ix_quality_reports_document_id'), table_name='quality_reports')
    op.drop_index(op.f('ix_quality_reports_run_id'), table_name='quality_reports')
    op.drop_table('quality_reports')
    sa.Enum(name='quality_report_status').drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f('ix_pii_detections_document_id'), table_name='pii_detections')
    op.drop_index(op.f('ix_pii_detections_run_id'), table_name='pii_detections')
    op.drop_table('pii_detections')
    sa.Enum(name='pii_action').drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f('ix_dictionary_applications_document_id'), table_name='dictionary_applications')
    op.drop_index(op.f('ix_dictionary_applications_step_id'), table_name='dictionary_applications')
    op.drop_index(op.f('ix_dictionary_applications_run_id'), table_name='dictionary_applications')
    op.drop_table('dictionary_applications')
    sa.Enum(name='dictionary_application_type').drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f('ix_cleaning_changes_document_id'), table_name='cleaning_changes')
    op.drop_index(op.f('ix_cleaning_changes_step_id'), table_name='cleaning_changes')
    op.drop_index(op.f('ix_cleaning_changes_run_id'), table_name='cleaning_changes')
    op.drop_table('cleaning_changes')

    op.drop_index(op.f('ix_document_chunks_run_id'), table_name='document_chunks')
    op.drop_index(op.f('ix_document_chunks_document_id'), table_name='document_chunks')
    op.drop_table('document_chunks')

    op.drop_table('cleaning_rules')
    sa.Enum(name='cleaning_rule_scope').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='cleaning_rule_type').drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f('ix_document_nodes_run_id'), table_name='document_nodes')
    op.drop_index(op.f('ix_document_nodes_document_id'), table_name='document_nodes')
    op.drop_table('document_nodes')
    sa.Enum(name='document_node_type').drop(op.get_bind(), checkfirst=True)
