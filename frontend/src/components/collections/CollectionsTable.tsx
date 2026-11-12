import { useState } from 'react'
import { BarChart3, Layers, Loader2, Pencil, Trash2, Users } from 'lucide-react'
import type { Collection } from '../../hooks/useCollections'
import { Badge, Button, IconButton } from '../ui'

export interface EmbeddingModelOption {
  key: string
  label: string
}

interface CollectionsTableProps {
  items: Collection[]
  embeddingModels: EmbeddingModelOption[]
  isAdmin: boolean
  isDeleting: boolean
  onOpenDocuments: (collection: Collection) => void
  onShare: (collection: Collection) => void
  onEdit: (collection: Collection) => void
  onGoldenEval: (collection: Collection) => void
  onVectorStats: (collection: Collection) => void
  onDelete: (collectionId: string) => Promise<void>
}

const CANNOT_EDIT_TITLE = '편집 권한이 있어야 수정할 수 있습니다'

// 재임베딩 상태 줄. 진행 중이면 스피너, 실패하면 경고 글자로 보여 준다.
function ReembedNote({ collection }: { collection: Collection }) {
  if (collection.reembed_status === 'PENDING' || collection.reembed_status === 'RUNNING') {
    return (
      <span className="ds-cell-sub" style={{ color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}>
        <Loader2 size={11} aria-hidden="true" style={{ animation: 'spin 1s linear infinite' }} />
        재임베딩 중 {collection.reembed_progress}
      </span>
    )
  }
  if (collection.reembed_status === 'FAILED') {
    return (
      <span className="ds-cell-sub" style={{ color: 'var(--color-danger)' }} title={collection.reembed_progress ?? undefined}>
        재임베딩 일부 실패
      </span>
    )
  }
  return null
}

function RowActions({
  collection, isAdmin, isDeleting, onShare, onEdit, onGoldenEval, onVectorStats, onDelete,
}: {
  collection: Collection
  isAdmin: boolean
  isDeleting: boolean
  onShare: () => void
  onEdit: () => void
  onGoldenEval: () => void
  onVectorStats: () => void
  onDelete: () => Promise<void>
}) {
  const [isConfirming, setIsConfirming] = useState(false)
  const canEdit = collection.is_owner || collection.role === 'editor'

  if (isConfirming) {
    return (
      <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', whiteSpace: 'nowrap' }}>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>삭제하시겠습니까?</span>
        <Button size="sm" variant="danger" disabled={isDeleting} onClick={async () => {
          await onDelete()
          setIsConfirming(false)
        }}>
          확인
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setIsConfirming(false)}>취소</Button>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 'var(--space-1)', alignItems: 'center' }}>
      {collection.is_owner && (
        <IconButton label="공유" onClick={onShare}><Users size={16} aria-hidden="true" /></IconButton>
      )}
      <IconButton
        label="수정"
        title={canEdit ? '수정' : CANNOT_EDIT_TITLE}
        onClick={onEdit}
        disabled={!canEdit}
      >
        <Pencil size={16} aria-hidden="true" />
      </IconButton>
      <IconButton label="골든 쿼리 평가" onClick={onGoldenEval}><BarChart3 size={16} aria-hidden="true" /></IconButton>
      <IconButton label="벡터 DB 현황" onClick={onVectorStats}><Layers size={16} aria-hidden="true" /></IconButton>
      {(collection.is_owner || isAdmin) && (
        <IconButton label="삭제" tone="danger" onClick={() => setIsConfirming(true)}>
          <Trash2 size={16} aria-hidden="true" />
        </IconButton>
      )}
    </div>
  )
}

/** 컬렉션 목록 표. 행의 작업 단추는 부모가 준 콜백을 호출한다. */
export function CollectionsTable({
  items, embeddingModels, isAdmin, isDeleting,
  onOpenDocuments, onShare, onEdit, onGoldenEval, onVectorStats, onDelete,
}: CollectionsTableProps) {
  return (
    <div className="ds-table-wrap">
      <table className="ds-table" aria-label="컬렉션 목록">
        <thead>
          <tr>
            <th scope="col">이름</th>
            <th scope="col">설명</th>
            <th scope="col">임베딩 모델</th>
            <th scope="col">청킹</th>
            <th scope="col">생성일</th>
            <th scope="col"><span className="sr-only">작업</span></th>
          </tr>
        </thead>
        <tbody>
          {items.map((col) => (
            <tr key={col.id}>
              <td>
                <button
                  type="button"
                  onClick={() => onOpenDocuments(col)}
                  title="이 컬렉션의 문서 보기"
                  style={{
                    background: 'none', border: 0, padding: 0, font: 'inherit', fontWeight: 600,
                    color: 'var(--color-primary)', cursor: 'pointer', textAlign: 'left',
                  }}
                >
                  {col.name}
                </button>
                <span style={{ display: 'inline-flex', gap: 'var(--space-1)', marginLeft: 'var(--space-2)', verticalAlign: 'middle' }}>
                  {col.project_name && (
                    <Badge tone="neutral" title={`${col.project_name} 프로젝트에 속함`}>{col.project_name}</Badge>
                  )}
                  {!col.is_owner && (
                    <Badge tone="info" title={`${col.role === 'editor' ? '편집자' : '조회자'} 권한으로 공유받음`}>공유받음</Badge>
                  )}
                </span>
              </td>
              <td className="ds-cell-muted">{col.description ?? '—'}</td>
              <td>
                {embeddingModels.find((m) => m.key === col.embedding_model)?.label ?? col.embedding_model}
                <ReembedNote collection={col} />
              </td>
              <td className="ds-cell-muted" style={{ whiteSpace: 'nowrap' }}>
                {col.chunk_max_tokens}자 / 겹침 {col.chunk_overlap_tokens}자
              </td>
              <td className="ds-cell-muted" style={{ whiteSpace: 'nowrap' }}>
                {new Date(col.created_at).toLocaleDateString('ko-KR')}
              </td>
              <td>
                <RowActions
                  collection={col}
                  isAdmin={isAdmin}
                  isDeleting={isDeleting}
                  onShare={() => onShare(col)}
                  onEdit={() => onEdit(col)}
                  onGoldenEval={() => onGoldenEval(col)}
                  onVectorStats={() => onVectorStats(col)}
                  onDelete={() => onDelete(col.id)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
