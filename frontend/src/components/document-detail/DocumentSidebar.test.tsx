import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import type { ComponentProps } from 'react'
import DocumentSidebar from './DocumentSidebar'
import { DOCUMENT_LANGUAGE_OPTIONS, documentLanguageLabel } from './documentDetailHelpers'
import type { Document } from '../../hooks/useDocuments'

// 접근 허용 패널은 자체 쿼리를 쓰므로 AccessPanel.test.tsx에서 따로 검증한다.
vi.mock('./AccessPanel', () => ({ default: () => null }))

type SidebarProps = ComponentProps<typeof DocumentSidebar>

const createDocument = (overrides: Partial<Document> = {}): Document => ({
  id: 'doc-1',
  filename: 'sample.pdf',
  original_filename: 'sample.pdf',
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
  lineage_id: 'doc-1',
  version_number: 1,
  lifecycle_state: 'current',
  expires_at: null,
  archived_at: null,
  title: 'Quarterly report',
  language: 'ko',
  category: 'report',
  page_count: 3,
  author: null,
  organization: null,
  security_level: null,
  source_system: null,
  checksum: null,
  parser_version: null,
  source_path: null,
  file_type: null,
  document_created_at: null,
  user_edited_fields: [],
  ...overrides,
})

const renderSidebar = (overrides: Partial<Document> = {}) => {
  const updateMetadata = { mutate: vi.fn() }
  const props: SidebarProps = {
    doc: createDocument(overrides),
    isReady: false,
    isProcessing: false,
    isAnalyzing: false,
    chunksResult: undefined,
    qualityReport: undefined,
    latestRun: null,
    updateMetadata: updateMetadata as unknown as SidebarProps['updateMetadata'],
    updateTags: { mutate: vi.fn() } as unknown as SidebarProps['updateTags'],
    acceptSuggestion: { mutate: vi.fn() } as unknown as SidebarProps['acceptSuggestion'],
    dismissSuggestion: { mutate: vi.fn() } as unknown as SidebarProps['dismissSuggestion'],
    tagInput: '',
    onTagInputChange: vi.fn(),
    onActiveTabChange: vi.fn(),
  }
  render(<DocumentSidebar {...props} />)
  return { updateMetadata }
}

// Row는 라벨 span과 값 span을 가진 grid div다. 라벨의 부모가 행 전체.
const getRow = (label: string): HTMLElement => {
  const row = screen.getByText(label).parentElement
  if (!row) throw new Error(`row not found: ${label}`)
  return row
}

describe('documentLanguageLabel', () => {
  it('저장된 언어 코드를 한국어 라벨로 바꾼다', () => {
    expect(documentLanguageLabel('ko')).toBe('한국어')
    expect(documentLanguageLabel('en')).toBe('영어')
    expect(documentLanguageLabel('ja')).toBe('일본어')
    expect(documentLanguageLabel('zh')).toBe('중국어')
  })

  it('알 수 없는 코드는 가공하지 않고 그대로 보여 준다', () => {
    expect(documentLanguageLabel('fr')).toBe('fr')
  })

  it('선택지는 네 가지 언어 코드를 모두 포함한다', () => {
    expect(DOCUMENT_LANGUAGE_OPTIONS.map((option) => option.code)).toEqual(['ko', 'en', 'ja', 'zh'])
  })
})

describe('DocumentSidebar 제목/언어/분류 편집', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('언어가 없으면 select에 미판별이 표시된다', () => {
    renderSidebar({ language: null })
    expect(screen.getByLabelText('언어')).toHaveDisplayValue('미판별')
  })

  it('언어 select에서 고르면 language 값으로 mutate를 호출한다', () => {
    const { updateMetadata } = renderSidebar({ language: 'ko' })
    fireEvent.change(screen.getByLabelText('언어'), { target: { value: 'ja' } })
    expect(updateMetadata.mutate).toHaveBeenCalledWith({ documentId: 'doc-1', language: 'ja' })
  })

  it('분류가 없으면 미분류가 표시된다', () => {
    renderSidebar({ category: null })
    expect(within(getRow('분류')).getByText('미분류')).toBeInTheDocument()
  })

  it('제목이 비어 있으면 제목 필드는 파일명을 흐리게 보여 준다', () => {
    renderSidebar({ title: null })
    expect(within(getRow('제목')).getByText('sample.pdf')).toBeInTheDocument()
  })

  it('제목을 빈 값으로 저장할 수 없도록 저장 버튼을 비활성화한다', () => {
    renderSidebar({ title: 'Quarterly report' })
    const row = getRow('제목')
    fireEvent.click(within(row).getByRole('button', { name: '편집' }))
    fireEvent.change(within(row).getByRole('textbox'), { target: { value: '   ' } })
    expect(within(row).getByRole('button', { name: '제목 저장' })).toBeDisabled()
  })

  it('제목을 입력하면 trim한 값으로 title mutate를 호출한다', () => {
    const { updateMetadata } = renderSidebar({ title: 'Quarterly report' })
    const row = getRow('제목')
    fireEvent.click(within(row).getByRole('button', { name: '편집' }))
    fireEvent.change(within(row).getByRole('textbox'), { target: { value: '  Annual report  ' } })
    fireEvent.click(within(row).getByRole('button', { name: '제목 저장' }))
    expect(updateMetadata.mutate).toHaveBeenCalledWith({ documentId: 'doc-1', title: 'Annual report' })
  })

  it('분류 입력 필드는 50자까지만 받는다', () => {
    renderSidebar({ category: 'report' })
    const row = getRow('분류')
    fireEvent.click(within(row).getByRole('button', { name: '편집' }))
    expect(within(row).getByRole('textbox')).toHaveAttribute('maxLength', '50')
  })
})

describe('직접 수정됨 배지와 자동값 복원', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('직접 수정한 필드가 없으면 배지가 나타나지 않는다', () => {
    renderSidebar({ user_edited_fields: [] })
    expect(screen.queryByText('직접 수정됨')).not.toBeInTheDocument()
  })

  it('직접 수정된 필드에만 배지가 나타난다', () => {
    renderSidebar({ user_edited_fields: ['language'] })
    expect(screen.getAllByText('직접 수정됨')).toHaveLength(1)
    expect(within(getRow('언어')).getByText('직접 수정됨')).toBeInTheDocument()
    expect(within(getRow('제목')).queryByText('직접 수정됨')).not.toBeInTheDocument()
    expect(within(getRow('분류')).queryByText('직접 수정됨')).not.toBeInTheDocument()
  })

  it('자동값으로 되돌리기 안내 문구를 함께 보여 준다', () => {
    renderSidebar({ user_edited_fields: ['category'] })
    expect(within(getRow('분류')).getByText('다음 처리 때 자동 생성됩니다')).toBeInTheDocument()
  })

  it.each([
    { field: 'title', label: '제목' },
    { field: 'language', label: '언어' },
    { field: 'category', label: '분류' },
  ] as const)('$field 되돌리기는 reset_fields만 담아 mutate를 호출한다', ({ field, label }) => {
    const { updateMetadata } = renderSidebar({ user_edited_fields: [field] })
    fireEvent.click(within(getRow(label)).getByRole('button', { name: '자동값으로 되돌리기' }))
    expect(updateMetadata.mutate).toHaveBeenCalledTimes(1)
    expect(updateMetadata.mutate).toHaveBeenCalledWith({ documentId: 'doc-1', reset_fields: [field] })
  })
})

describe('분류 PENDING 안내', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('자동 분석이 실행되지 않고 분류가 비어 있으면 안내를 보여 준다', () => {
    renderSidebar({ metadata_status: 'PENDING', category: null })
    expect(
      screen.getByText('자동 분석이 실행되지 않아 비어 있습니다. 직접 입력할 수 있습니다.'),
    ).toBeInTheDocument()
  })

  it('분류 값이 있으면 PENDING이어도 안내를 보여 주지 않는다', () => {
    renderSidebar({ metadata_status: 'PENDING', category: 'report' })
    expect(screen.queryByText(/자동 분석이 실행되지 않아/)).not.toBeInTheDocument()
  })

  it('자동 분석이 끝난 상태에서 분류가 비어 있어도 안내를 보여 주지 않는다', () => {
    renderSidebar({ metadata_status: 'DONE', category: null })
    expect(screen.queryByText(/자동 분석이 실행되지 않아/)).not.toBeInTheDocument()
  })
})
