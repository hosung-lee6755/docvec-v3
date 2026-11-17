import { useRef, useState, type DragEvent, type ReactNode } from 'react'
import { Upload } from 'lucide-react'
import { Button } from '../ui'
import { hasExtension } from '../../lib/uploadFormats'

interface FileDropzoneProps {
  testId: string
  extensions: readonly string[]
  isMultiple?: boolean
  onClick: () => void
  // 받을 수 있는 파일과 형식이 맞지 않아 뺀 파일을 함께 넘긴다
  onFiles: (accepted: File[], rejected: File[]) => void
  children: ReactNode
}

function carriesFiles(e: DragEvent) {
  return Array.from(e.dataTransfer?.types ?? []).includes('Files')
}

/** 버튼을 눌러 고르거나, 탐색기에서 파일을 끌어다 놓아 고른다. */
export function FileDropzone({ testId, extensions, isMultiple = false, onClick, onFiles, children }: FileDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false)
  // 안쪽 요소(버튼 글자 등)를 지날 때마다 enter/leave가 번갈아 와서, 깊이를 세어 깜빡임을 막는다
  const depth = useRef(0)

  const handleDragEnter = (e: DragEvent) => {
    if (!carriesFiles(e)) return
    e.preventDefault()
    depth.current += 1
    setIsDragging(true)
  }
  const handleDragLeave = (e: DragEvent) => {
    if (!carriesFiles(e)) return
    depth.current = Math.max(0, depth.current - 1)
    if (depth.current === 0) setIsDragging(false)
  }
  const handleDragOver = (e: DragEvent) => {
    if (!carriesFiles(e)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }
  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    depth.current = 0
    setIsDragging(false)
    const dropped = Array.from(e.dataTransfer?.files ?? [])
    const picked = isMultiple ? dropped : dropped.slice(0, 1)
    const accepted = picked.filter((f) => hasExtension(f.name, extensions))
    const rejected = dropped.filter((f) => !accepted.includes(f))
    onFiles(accepted, rejected)
  }

  return (
    <div
      data-testid={testId}
      className={`documents-drop-area${isDragging ? ' is-dragging' : ''}`}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <Button variant="secondary" className="documents-dropzone" icon={<Upload size={16} />} onClick={onClick}>
        {children}
      </Button>
      <span className="documents-drop-hint" aria-hidden="true">
        {isDragging ? '여기에 놓으면 추가됩니다' : '또는 파일을 이 영역으로 끌어다 놓으세요'}
      </span>
    </div>
  )
}
