import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DocumentsTable } from './DocumentsTable'
import type { Document } from '../../hooks/useDocuments'

const document = (overrides: Partial<Document>): Document => ({
  id: 'doc-1',
  filename: 'report.pdf',
  original_filename: 'report.pdf',
  status: 'INDEXED',
  file_size: 2048,
  collection_id: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  error_message: null,
  parsed_text: null,
  ocr_used: false,
  summary: null,
  summary_status: 'PENDING',
  tags: [],
  suggested_tags: [],
  metadata_status: 'DONE',
  active_run_id: null,
  title: null,
  language: null,
  category: null,
  page_count: null,
  author: null,
  organization: null,
  security_level: null,
  source_system: null,
  checksum: null,
  parser_version: null,
  source_path: null,
  file_type: null,
  document_created_at: null,
  lineage_id: 'doc-1',
  version_number: 1,
  lifecycle_state: 'current',
  expires_at: null,
  archived_at: null,
  ...overrides,
})

const renderTable = (documents: Document[]) => {
  const noop = vi.fn()
  return render(
    <DocumentsTable
      documents={documents}
      sortBy="created_at"
      order="desc"
      selectedIds={new Set()}
      confirmDeleteId={null}
      collectionsMap={{}}
      onToggleSort={noop}
      onToggleSelect={noop}
      onToggleAll={noop}
      onConfirmDelete={noop}
      onCancelDelete={noop}
      onDeleteClick={noop}
      onDocumentClick={noop}
      isDeleting={false}
    />,
  )
}

describe('DocumentsTable lifecycle badges', () => {
  it('shows no lifecycle badge for a plain first-version current document', () => {
    renderTable([document({})])
    expect(screen.queryByText(/^v\d+$/)).not.toBeInTheDocument()
    expect(screen.queryByText('보관됨')).not.toBeInTheDocument()
  })

  it('shows the version number from the second version on', () => {
    renderTable([document({ version_number: 3 })])
    expect(screen.getByText('v3')).toBeInTheDocument()
  })

  it('labels archived, superseded and pending versions', () => {
    renderTable([
      document({ id: 'a', lifecycle_state: 'archived' }),
      document({ id: 'b', lifecycle_state: 'superseded', version_number: 2 }),
      document({ id: 'c', lifecycle_state: 'pending', status: 'EMBEDDING', version_number: 2 }),
    ])
    expect(screen.getByText('보관됨')).toBeInTheDocument()
    expect(screen.getByText('이전 버전')).toBeInTheDocument()
    expect(screen.getByText('새 버전 처리 중')).toBeInTheDocument()
  })

  it('shows the expiry date in local calendar time', () => {
    renderTable([document({ expires_at: new Date(2026, 11, 31, 12).toISOString() })])
    expect(screen.getByText('만료 2026-12-31')).toBeInTheDocument()
  })
})
