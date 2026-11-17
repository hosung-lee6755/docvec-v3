import { useState } from 'react'
import { FolderInput } from 'lucide-react'

interface CollectionOption {
  id: string
  name: string
}

interface MoveCollectionControlProps {
  collections: CollectionOption[]
  // 지금 문서가 있는 컬렉션. 한 문서를 옮길 때만 알 수 있어 선택지에서 뺀다
  currentCollectionId?: string | null
  isPending: boolean
  onMove: (collectionId: string) => void
  // 일괄 작업 막대 밖(문서 상세 머리)에서는 디자인 시스템 버튼 모양을 쓴다
  buttonClassName?: string
}

/** "컬렉션 이동" 버튼을 누르면 대상 컬렉션을 고르는 칸과 확인 버튼이 펼쳐진다. */
export default function MoveCollectionControl({
  collections, currentCollectionId, isPending, onMove, buttonClassName,
}: MoveCollectionControlProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [targetId, setTargetId] = useState('')
  const options = collections.filter((c) => c.id !== currentCollectionId)

  if (!isOpen) {
    return (
      <button type="button" className={buttonClassName} onClick={() => setIsOpen(true)} disabled={isPending}>
        <FolderInput size={12} aria-hidden="true" /> 컬렉션 이동
      </button>
    )
  }
  const close = () => { setIsOpen(false); setTargetId('') }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <select
        aria-label="옮길 컬렉션"
        value={targetId}
        onChange={(e) => setTargetId(e.target.value)}
        disabled={isPending}
        style={{ fontSize: 12, padding: '2px 6px' }}
      >
        <option value="">옮길 컬렉션 선택</option>
        {options.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
      <button type="button" className={buttonClassName} disabled={!targetId || isPending} onClick={() => { onMove(targetId); close() }}>
        {isPending ? '옮기는 중...' : '이동'}
      </button>
      <button type="button" className={buttonClassName} onClick={close} disabled={isPending}>취소</button>
    </span>
  )
}
