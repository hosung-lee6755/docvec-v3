import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { UploadModal } from './UploadModal'

vi.mock('../../hooks/useDocuments', () => ({
  useUploadDocument: () => ({ mutateAsync: vi.fn() }),
  useUploadZip: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('../../hooks/useCollections', () => ({
  useCollections: () => ({ data: { items: [{ id: 'c1', name: '규정', project_id: null }] } }),
}))
vi.mock('../../hooks/useWorkflows', () => ({
  useWorkflows: () => ({ data: { items: [] } }),
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
