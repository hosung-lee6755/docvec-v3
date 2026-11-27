import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { UploadModal } from './UploadModal'

const mocks = vi.hoisted(() => ({
  upload: vi.fn(async (_input: Record<string, unknown>) => ({ version_number: 1 })),
  collectionsFor: vi.fn((_projectId?: string | null) => [{ id: 'c1', name: '규정', project_id: null as string | null }]),
  workflowsFor: vi.fn((_projectId: string | null, _kind: string) => [] as { id: string; name: string; project_id: string | null }[]),
}))

vi.mock('../../hooks/useDocuments', () => ({
  useUploadDocument: () => ({ mutateAsync: mocks.upload }),
  useUploadZip: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('../../hooks/useCollections', () => ({
  useCollections: (projectId?: string | null) => ({ data: { items: mocks.collectionsFor(projectId) } }),
}))
vi.mock('../../hooks/useWorkflows', () => ({
  useWorkflows: (projectId: string | null, kind: string) => ({ data: { items: mocks.workflowsFor(projectId, kind) } }),
  useWorkflowVersions: () => ({ data: { items: [] } }),
}))

function dropFiles(target: Element, files: File[]) {
  fireEvent.dragOver(target, { dataTransfer: { files, types: ['Files'] } })
  fireEvent.drop(target, { dataTransfer: { files, types: ['Files'] } })
}

describe('UploadModal drag and drop', () => {
  it('adds dropped files to the selection', () => {
    render(<UploadModal isOpen onClose={() => {}} />)

    dropFiles(screen.getByTestId('upload-dropzone'), [
      new File(['a'], '매출.csv', { type: 'text/csv' }),
      new File(['b'], '규정.pdf', { type: 'application/pdf' }),
    ])

    expect(screen.getByText('매출.csv')).toBeTruthy()
    expect(screen.getByText('규정.pdf')).toBeTruthy()
    expect(screen.getByRole('button', { name: /2개 파일 선택됨/ })).toBeTruthy()
  })

  it('skips unsupported files and says which ones', () => {
    render(<UploadModal isOpen onClose={() => {}} />)

    dropFiles(screen.getByTestId('upload-dropzone'), [
      new File(['a'], '설치.exe'),
      new File(['b'], '메모.txt', { type: 'text/plain' }),
    ])

    expect(screen.getByText('메모.txt')).toBeTruthy()
    expect(screen.queryByText('설치.exe')).toBeNull()
    expect(screen.getByRole('status').textContent).toContain('설치.exe')
  })

  it('shows a highlight while files are dragged over', () => {
    render(<UploadModal isOpen onClose={() => {}} />)
    const zone = screen.getByTestId('upload-dropzone')

    fireEvent.dragEnter(zone, { dataTransfer: { files: [], types: ['Files'] } })
    expect(zone.className).toContain('is-dragging')

    fireEvent.dragLeave(zone, { dataTransfer: { files: [], types: ['Files'] } })
    expect(zone.className).not.toContain('is-dragging')
  })

  it('accepts csv in the file picker', () => {
    render(<UploadModal isOpen onClose={() => {}} />)

    const input = screen.getByLabelText('업로드할 파일') as HTMLInputElement
    expect(input.accept.split(',')).toContain('.csv')
  })

  it('takes a dropped zip in zip mode', () => {
    render(<UploadModal isOpen onClose={() => {}} />)
    fireEvent.click(screen.getByRole('tab', { name: 'ZIP 일괄 업로드' }))

    dropFiles(screen.getByTestId('upload-zip-dropzone'), [new File(['z'], '묶음.zip', { type: 'application/zip' })])

    expect(screen.getByRole('button', { name: /묶음\.zip/ })).toBeTruthy()
  })
})

describe('UploadModal project scope and analysis workflow', () => {
  it('lists only the collections of the project it was opened from', () => {
    mocks.collectionsFor.mockClear()

    render(<UploadModal isOpen onClose={() => {}} projectId="p1" />)

    expect(mocks.collectionsFor).toHaveBeenCalledWith('p1')
  })

  it('offers the project analysis workflows and sends the chosen one with the upload', async () => {
    mocks.collectionsFor.mockReturnValue([{ id: 'c2', name: '공정 문서', project_id: 'p1' }])
    mocks.workflowsFor.mockImplementation((projectId, kind) =>
      projectId === 'p1'
        ? [{ id: kind === 'ANALYSIS' ? 'a1' : 'w1', name: kind === 'ANALYSIS' ? '공정 분석' : '공정 전처리', project_id: 'p1' }]
        : [])
    render(<UploadModal isOpen onClose={() => {}} projectId="p1" />)

    fireEvent.change(screen.getByLabelText(/컬렉션/), { target: { value: 'c2' } })
    fireEvent.change(screen.getByLabelText('분석 워크플로우'), { target: { value: 'a1' } })
    dropFiles(screen.getByTestId('upload-dropzone'), [new File(['a'], '보고서.pdf', { type: 'application/pdf' })])
    fireEvent.click(screen.getByRole('button', { name: '업로드' }))

    await waitFor(() => expect(mocks.upload).toHaveBeenCalled())
    expect(mocks.upload.mock.calls[0][0]).toMatchObject({ collection_id: 'c2', analysis_workflow_id: 'a1' })
    expect(mocks.workflowsFor).toHaveBeenCalledWith('p1', 'ANALYSIS')
  })
})

describe('UploadModal opened from a collection', () => {
  it('starts with the collection the documents page is showing', () => {
    mocks.collectionsFor.mockReturnValue([
      { id: 'c2', name: '공정 문서', project_id: 'p1' },
      { id: 'c3', name: '회의록', project_id: 'p1' },
    ])
    mocks.workflowsFor.mockReturnValue([])

    render(<UploadModal isOpen onClose={() => {}} projectId="p1" defaultCollectionId="c3" />)

    expect((screen.getByLabelText(/컬렉션/) as HTMLSelectElement).value).toBe('c3')
    expect(screen.getByLabelText('분석 워크플로우')).toBeTruthy()
  })
})

describe('UploadModal document type', () => {
  it('sends the batch type and lets one file override it', async () => {
    mocks.upload.mockClear()
    mocks.collectionsFor.mockReturnValue([{ id: 'c1', name: '규정', project_id: null }])
    mocks.workflowsFor.mockReturnValue([])
    render(<UploadModal isOpen onClose={() => {}} defaultCollectionId="c1" />)

    fireEvent.change(screen.getByLabelText('문서 유형'), { target: { value: 'regulation' } })
    dropFiles(screen.getByTestId('upload-dropzone'), [
      new File(['a'], '휴직규정.pdf', { type: 'application/pdf' }),
      new File(['b'], '결과보고서.pdf', { type: 'application/pdf' }),
    ])
    fireEvent.change(screen.getByLabelText('결과보고서.pdf 문서 유형'), { target: { value: 'general' } })
    fireEvent.click(screen.getByRole('button', { name: '2개 업로드' }))

    await waitFor(() => expect(mocks.upload).toHaveBeenCalledTimes(2))
    expect(mocks.upload.mock.calls[0][0]).toMatchObject({ document_type: 'regulation' })
    expect(mocks.upload.mock.calls[1][0]).toMatchObject({ document_type: 'general' })
  })

  it('leaves the type to the collection default when nothing is chosen', async () => {
    mocks.upload.mockClear()
    mocks.collectionsFor.mockReturnValue([
      { id: 'c1', name: '규정', project_id: null, default_document_type: 'regulation' } as never,
    ])
    render(<UploadModal isOpen onClose={() => {}} defaultCollectionId="c1" />)

    expect(screen.getByRole('option', { name: '컬렉션 기본값 (규정·법령)' })).toBeTruthy()
    dropFiles(screen.getByTestId('upload-dropzone'), [new File(['a'], '규정.pdf', { type: 'application/pdf' })])
    fireEvent.click(screen.getByRole('button', { name: '업로드' }))

    await waitFor(() => expect(mocks.upload).toHaveBeenCalled())
    expect(mocks.upload.mock.calls[0][0].document_type).toBeUndefined()
  })
})
