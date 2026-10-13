import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClientProvider, QueryClient } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import DocumentDetailPage from './DocumentDetailPage'

// Mock all hooks used by DocumentDetailPage
vi.mock('../hooks/useDocuments')
vi.mock('../hooks/useDocumentRuns')
vi.mock('../hooks/useWorkflows')
vi.mock('../hooks/useDocumentMetadata')
vi.mock('../hooks/useDocumentStructure')
vi.mock('../components/document-detail/StructureTab', () => ({
  default: () => <div data-testid="structure-tab">StructureTab</div>,
}))
vi.mock('../components/document-detail/ElementsTab', () => ({
  default: () => <div data-testid="elements-tab">ElementsTab</div>,
}))
vi.mock('../components/document-detail/CleaningChangesTab', () => ({
  default: () => <div data-testid="cleaning-tab">CleaningChangesTab</div>,
}))
vi.mock('../components/document-detail/DictionaryApplicationsTab', () => ({
  default: () => <div data-testid="dict-tab">DictionaryApplicationsTab</div>,
}))
vi.mock('../components/document-detail/PiiDetectionsTab', () => ({
  default: () => <div data-testid="pii-tab">PiiDetectionsTab</div>,
}))
vi.mock('../components/workflow/StepTimeline', () => ({
  default: () => <div data-testid="step-timeline">StepTimeline</div>,
}))
vi.mock('../components/ReprocessModal', () => ({
  default: () => <div data-testid="reprocess-modal">ReprocessModal</div>,
}))

import * as useDocumentsModule from '../hooks/useDocuments'
import * as useDocumentRunsModule from '../hooks/useDocumentRuns'
import * as useWorkflowsModule from '../hooks/useWorkflows'
import * as useDocumentMetadataModule from '../hooks/useDocumentMetadata'
import * as useDocumentStructureModule from '../hooks/useDocumentStructure'
import { mockHook } from '../test/mockHook'

const createQueryClient = () => new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})

const renderPage = (initialRoute = '/documents/test-doc') => {
  const queryClient = createQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <Routes>
          <Route path="/documents/:id" element={<DocumentDetailPage />} />
          <Route path="/documents" element={<div data-testid="documents-list">Documents List</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

const createMockDocument = (overrides = {}) => ({
  id: 'test-doc',
  original_filename: 'test.pdf',
  status: 'INDEXED',
  file_size: 1024000,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  title: 'Test Document',
  tags: [],
  ...overrides,
})

describe('DocumentDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default mocks return empty/false
    mockHook(useDocumentsModule.useDocument, {
      data: undefined,
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentsModule.useDocumentContent, {
      data: undefined,
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentsModule.useDocumentChunks, {
      data: undefined,
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentsModule.useDocumentTables, {
      data: undefined,
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentsModule.useDocumentImages, {
      data: undefined,
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentsModule.useDocumentPreview, {
      data: undefined,
      isError: false,
    })
    mockHook(useDocumentsModule.useDocumentPagesText, {
      data: undefined,
    })
    mockHook(useDocumentsModule.useDocumentRevisions, {
      data: undefined,
    })
    mockHook(useDocumentsModule.useDownloadDocument, {
      mutate: vi.fn(),
      isPending: false,
    })
    mockHook(useDocumentsModule.useProceedDocument, {
      mutate: vi.fn(),
      isPending: false,
      isError: false,
    })
    mockHook(useDocumentsModule.useReprocessDocument, {
      mutate: vi.fn(),
      isPending: false,
      isError: false,
    })
    mockHook(useDocumentsModule.useRetryDocument, {
      mutate: vi.fn(),
      isPending: false,
    })
    mockHook(useDocumentsModule.useUpdateChunk, {
      mutate: vi.fn(),
      isPending: false,
    })
    mockHook(useDocumentsModule.useDeleteChunk, {
      mutate: vi.fn(),
      isPending: false,
    })
    mockHook(useDocumentsModule.useRestoreRevision, {
      mutate: vi.fn(),
      isPending: false,
    })
    mockHook(useDocumentsModule.useUpdateDocumentTags, {
      mutate: vi.fn(),
    })
    mockHook(useDocumentsModule.useAcceptTagSuggestion, {
      mutate: vi.fn(),
    })
    mockHook(useDocumentsModule.useDismissTagSuggestion, {
      mutate: vi.fn(),
    })
    mockHook(useDocumentRunsModule.useDocumentRuns, {
      data: undefined,
    })
    mockHook(useDocumentRunsModule.useDocumentQuality, {
      data: undefined,
    })
    mockHook(useWorkflowsModule.useWorkflowRun, {
      data: undefined,
    })
    mockHook(useWorkflowsModule.useCancelRun, {
      mutate: vi.fn(),
      isPending: false,
      isError: false,
    })
    mockHook(useWorkflowsModule.useResumeRun, {
      mutate: vi.fn(),
      isPending: false,
      isError: false,
    })
    mockHook(useDocumentMetadataModule.useUpdateDocumentMetadata, {
      mutate: vi.fn(),
    })
    mockHook(useDocumentStructureModule.useDocumentNodes, {
      data: undefined,
    })
  })

  it('displays loading message when document is loading', () => {
    mockHook(useDocumentsModule.useDocument, {
      data: undefined,
      isLoading: true,
      isError: false,
    })

    renderPage()
    expect(screen.getByText('로딩 중...')).toBeInTheDocument()
  })

  it('displays not found message when document does not exist', () => {
    mockHook(useDocumentsModule.useDocument, {
      data: null,
      isLoading: false,
      isError: false,
    })

    renderPage()
    expect(screen.getByText('문서를 불러올 수 없습니다.')).toBeInTheDocument()
  })

  it('renders document title and back button when document is loaded', () => {
    mockHook(useDocumentsModule.useDocument, {
      data: createMockDocument(),
      isLoading: false,
      isError: false,
    })

    renderPage()
    expect(screen.getByText('test.pdf')).toBeInTheDocument()
    expect(screen.getByText('문서 목록')).toBeInTheDocument()
  })

  it('displays metadata fields for UPLOADED status document', () => {
    const doc = createMockDocument({
      status: 'UPLOADED',
      title: 'Test Title',
      language: 'ko',
      page_count: 5,
    })

    mockHook(useDocumentsModule.useDocument, {
      data: doc,
      isLoading: false,
      isError: false,
    })

    renderPage()
    expect(screen.getByText('Test Title')).toBeInTheDocument()
    expect(screen.getByLabelText('언어')).toHaveDisplayValue('한국어')
  })

  it('renders tabs and panels when document is INDEXED', () => {
    mockHook(useDocumentsModule.useDocument, {
      data: createMockDocument({ status: 'INDEXED' }),
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentRunsModule.useDocumentRuns, {
      data: { runs: [] },
    })

    renderPage()
    expect(screen.getByText('분석 요약')).toBeInTheDocument()
    expect(screen.getByText('RAG 현황')).toBeInTheDocument()
  })

  it('displays review panel when document status is WAITING_REVIEW', () => {
    mockHook(useDocumentsModule.useDocument, {
      data: createMockDocument({ status: 'WAITING_REVIEW' }),
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentRunsModule.useDocumentRuns, {
      data: {
        runs: [
          {
            id: 'run-1',
            status: 'WAITING_REVIEW',
            trigger: 'UPLOAD',
            started_at: '2026-01-01T00:00:00Z',
          },
        ],
      },
    })
    mockHook(useDocumentsModule.useDocumentChunks, {
      data: { chunks: [] },
      isLoading: false,
      isError: false,
    })

    renderPage()
    expect(screen.getByText('이 문서는 검토 대기 중입니다')).toBeInTheDocument()
  })

  it('displays error information when document status is FAILED', () => {
    mockHook(useDocumentsModule.useDocument, {
      data: createMockDocument({
        status: 'FAILED',
        error_message: 'Processing failed',
      }),
      isLoading: false,
      isError: false,
    })

    renderPage()
    expect(screen.getByText('오류 정보')).toBeInTheDocument()
    expect(screen.getByText('Processing failed')).toBeInTheDocument()
  })

  it('renders metadata section with editable and read-only fields', () => {
    mockHook(useDocumentsModule.useDocument, {
      data: createMockDocument({
        title: 'Sample Title',
        author: 'John Doe',
        security_level: 'Confidential',
        tags: ['tag1', 'tag2'],
      }),
      isLoading: false,
      isError: false,
    })

    renderPage()
    expect(screen.getByText('Sample Title')).toBeInTheDocument()
    expect(screen.getByText('John Doe')).toBeInTheDocument()
    expect(screen.getByText('tag1')).toBeInTheDocument()
    expect(screen.getByText('tag2')).toBeInTheDocument()
  })

  it('shows chunks count in RAG status when chunks are available', () => {
    mockHook(useDocumentsModule.useDocument, {
      data: createMockDocument({ status: 'INDEXED' }),
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentsModule.useDocumentChunks, {
      data: {
        chunks: Array(5).fill(null).map((_, i) => ({
          id: `chunk-${i}`,
          chunk_index: i,
          text: `Chunk text ${i}`,
          embedded: true,
          disabled: false,
        })),
      },
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentRunsModule.useDocumentRuns, {
      data: { runs: [] },
    })

    renderPage()
    expect(screen.getByText(/5개/)).toBeInTheDocument()
  })

  it('loads quality report data when document is INDEXED', () => {
    mockHook(useDocumentsModule.useDocument, {
      data: createMockDocument({ status: 'INDEXED' }),
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentRunsModule.useDocumentQuality, {
      data: {
        overall_score: 85.5,
        status: 'SUCCESS',
        warnings: [],
      },
    })
    mockHook(useDocumentRunsModule.useDocumentRuns, {
      data: { runs: [] },
    })

    renderPage()
    // Quality report is loaded for INDEXED documents (visible in RAG status)
    expect(vi.mocked(useDocumentRunsModule.useDocumentQuality)).toHaveBeenCalled()
  })

  it('has tabs for navigation when INDEXED', () => {
    mockHook(useDocumentsModule.useDocument, {
      data: createMockDocument({ status: 'INDEXED' }),
      isLoading: false,
      isError: false,
    })
    mockHook(useDocumentRunsModule.useDocumentRuns, {
      data: { runs: [] },
    })

    renderPage()
    // Check for tab buttons
    expect(screen.getByRole('tab', { name: /품질/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /처리 이력/ })).toBeInTheDocument()
  })

  describe('mutation failures', () => {
    beforeEach(() => {
      mockHook(useDocumentsModule.useDocument, {
        data: createMockDocument({ status: 'INDEXED' }),
        isLoading: false,
        isError: false,
      })
      mockHook(useDocumentRunsModule.useDocumentRuns, { data: { runs: [] } })
    })

    it('tells the user when saving tags fails instead of silently doing nothing', () => {
      mockHook(useDocumentsModule.useUpdateDocumentTags, { mutate: vi.fn(), isError: true, reset: vi.fn() })

      renderPage()

      expect(screen.getByRole('alert')).toHaveTextContent('태그 저장에 실패했습니다')
    })

    it('shows nothing when no mutation has failed', () => {
      renderPage()

      expect(screen.queryByText(/에 실패했습니다/)).not.toBeInTheDocument()
    })

    it('lets the user dismiss a failure, which resets that mutation', () => {
      const reset = vi.fn()
      mockHook(useDocumentsModule.useDeleteChunk, { mutate: vi.fn(), isError: true, reset })

      renderPage()
      fireEvent.click(screen.getByRole('button', { name: '청크 삭제 오류 닫기' }))

      expect(reset).toHaveBeenCalledTimes(1)
    })

    it('lists every failed action at once', () => {
      mockHook(useDocumentMetadataModule.useUpdateDocumentMetadata, { mutate: vi.fn(), isError: true, reset: vi.fn() })
      mockHook(useDocumentsModule.useRestoreRevision, { mutate: vi.fn(), isError: true, reset: vi.fn() })

      renderPage()

      const alert = screen.getByRole('alert')
      expect(alert).toHaveTextContent('메타데이터 저장에 실패했습니다')
      expect(alert).toHaveTextContent('버전 복원에 실패했습니다')
    })
  })
})
