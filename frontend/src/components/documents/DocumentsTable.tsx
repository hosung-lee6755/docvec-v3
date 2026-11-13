import { ArrowDown, ArrowUp, Trash2 } from 'lucide-react'
import { type Document, type DocumentSortBy, type SortOrder } from '../../hooks/useDocuments'
import { formatLocalDate } from '../../lib/documentLifecycle'
import { Badge, IconButton, StatusBadge, Button } from '../ui'
import type { BadgeTone } from '../ui'
import { explainFailure } from '../../lib/apiError'
import '../../styles/screens/documents.css'

// 통과(SUCCESS)는 배지를 달지 않는다. 눈여겨볼 판정만 보인다.
const QUALITY_BADGES: Record<string, { label: string; tone: BadgeTone }> = {
  SUCCESS_WITH_WARNING: { label: '품질 경고', tone: 'warning' },
  REVIEW_REQUIRED: { label: '검토 필요', tone: 'warning' },
  PARTIAL_FAILURE: { label: '부분 실패', tone: 'danger' },
  FAILURE: { label: '품질 실패', tone: 'danger' },
}

interface DocumentBadge {
  key: string
  label: string
  tone: BadgeTone
  title?: string
}

// 버전·수명주기 배지. 현재 버전(current)이고 만료일이 없으면 아무것도 달지 않는다.
function lifecycleBadges(doc: Document): DocumentBadge[] {
  const badges: DocumentBadge[] = []
  if (doc.version_number > 1) {
    badges.push({ key: 'version', label: `v${doc.version_number}`, tone: 'info', title: `같은 문서의 ${doc.version_number}번째 버전입니다.` })
  }
  if (doc.lifecycle_state === 'archived') {
    badges.push({ key: 'archived', label: '보관됨', tone: 'neutral', title: '보관된 문서는 검색과 답변에 쓰이지 않습니다. 문서 상세에서 다시 꺼낼 수 있습니다.' })
  }
  if (doc.lifecycle_state === 'superseded') {
    badges.push({ key: 'superseded', label: '이전 버전', tone: 'neutral', title: '새 버전이 현재 버전이 되어 검색에서 빠졌습니다. 이력은 문서 상세에서 볼 수 있습니다.' })
  }
  if (doc.lifecycle_state === 'pending') {
    badges.push({ key: 'pending', label: '새 버전 처리 중', tone: 'info', title: '새 버전을 처리하는 중입니다. 완료되면 현재 버전이 됩니다.' })
  }
  if (doc.expires_at) {
    badges.push({ key: 'expires', label: `만료 ${formatLocalDate(doc.expires_at)}`, tone: 'warning', title: '만료일이 지나면 자동으로 보관됩니다.' })
  }
  return badges
}

// 검토 대기는 경고 행, 실패는 위험 행으로 눈에 띄게 한다.
const REVIEW_STATUSES = new Set(['WAITING_REVIEW', 'REVIEW_PENDING'])
function rowClassFor(doc: Document): string {
  if (doc.status === 'FAILED') return 'is-danger'
  if (REVIEW_STATUSES.has(doc.status)) return 'is-warning'
  return ''
}

const COLUMNS: [string, DocumentSortBy | null][] = [
  ['파일명', 'filename'],
  ['컬렉션', null],
  ['크기', 'file_size'],
  ['상태', 'status'],
  ['생성일', 'created_at'],
  ['', null],
]

interface DocumentsTableProps {
  documents: Document[] | undefined
  sortBy: DocumentSortBy
  order: SortOrder
  selectedIds: Set<string>
  confirmDeleteId: string | null
  collectionsMap: Record<string, string>
  onToggleSort: (column: DocumentSortBy) => void
  onToggleSelect: (id: string) => void
  onToggleAll: () => void
  onConfirmDelete: (id: string) => void
  onCancelDelete: () => void
  onDeleteClick: (id: string) => void
  onDocumentClick: (id: string) => void
  isDeleting: boolean
}

export function DocumentsTable({
  documents,
  sortBy,
  order,
  selectedIds,
  confirmDeleteId,
  collectionsMap,
  onToggleSort,
  onToggleSelect,
  onToggleAll,
  onConfirmDelete,
  onCancelDelete,
  onDeleteClick,
  onDocumentClick,
  isDeleting,
}: DocumentsTableProps) {
  return (
    <div className="ds-table-wrap">
      <table className="ds-table">
        <caption className="sr-only">문서 목록</caption>
        <thead>
          <tr>
            <th scope="col" className="ds-cell-check">
              <input
                type="checkbox"
                aria-label="전체 선택"
                checked={selectedIds.size > 0 && selectedIds.size === documents?.length}
                onChange={onToggleAll}
              />
            </th>
            {COLUMNS.map(([label, column]) => (
              <th
                key={label}
                scope="col"
                onClick={column ? () => onToggleSort(column) : undefined}
                style={{ cursor: column ? 'pointer' : 'default', userSelect: 'none' }}
              >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  {label}
                  {column && sortBy === column && (
                    order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {documents?.map((doc) => (
            <tr key={doc.id} className={[rowClassFor(doc), selectedIds.has(doc.id) ? 'is-selected' : ''].filter(Boolean).join(' ')}>
              <td className="ds-cell-check">
                <input
                  type="checkbox"
                  aria-label={`${doc.original_filename} 선택`}
                  checked={selectedIds.has(doc.id)}
                  onChange={() => onToggleSelect(doc.id)}
                />
              </td>
              <td>
                <button type="button" className="documents-link" onClick={() => onDocumentClick(doc.id)}>
                  {doc.original_filename}
                </button>
              </td>
              <td className="ds-cell-muted">
                {doc.collection_id
                  ? (collectionsMap[doc.collection_id] ?? doc.collection_id.slice(0, 8))
                  : '-'}
              </td>
              <td className="ds-cell-num ds-cell-muted">
                {(doc.file_size / 1024).toFixed(1)} KB
              </td>
              <td>
                <DocumentStatusCell doc={doc} />
              </td>
              <td className="ds-cell-muted">
                {new Date(doc.created_at).toLocaleDateString('ko-KR')}
              </td>
              <td>
                {confirmDeleteId === doc.id ? (
                  <div className="documents-cell-actions">
                    <span className="documents-text-danger">삭제하시겠습니까?</span>
                    <Button size="sm" variant="danger-solid" onClick={() => onConfirmDelete(doc.id)} disabled={isDeleting}>
                      확인
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => onCancelDelete()}>
                      취소
                    </Button>
                  </div>
                ) : (
                  <div className="documents-cell-actions">
                    <IconButton label="삭제" tone="danger" onClick={() => onDeleteClick(doc.id)}>
                      <Trash2 size={14} />
                    </IconButton>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DocumentStatusCell({ doc }: { doc: Document }) {
  const quality = QUALITY_BADGES[doc.quality_status ?? '']
  const extras: DocumentBadge[] = [
    ...(doc.ocr_used
      ? [{ key: 'ocr', label: 'OCR', tone: 'info' as const, title: '스캔 이미지 페이지를 OCR로 인식한 문서입니다.' }]
      : []),
    ...(quality
      ? [{ key: 'quality', label: quality.label, tone: quality.tone, title: '최근 처리의 품질 판정입니다. 문서 상세의 품질 탭에서 이유를 볼 수 있습니다.' }]
      : []),
    ...((doc.low_ocr_pages?.length ?? 0) > 0
      ? [{ key: 'low-ocr', label: `OCR 낮음 ${doc.low_ocr_pages?.length}쪽`, tone: 'warning' as const, title: `OCR 신뢰도가 기준보다 낮은 쪽: ${doc.low_ocr_pages?.join(', ')}` }]
      : []),
    ...lifecycleBadges(doc),
  ]
  return (
    <div className="documents-badges">
      <StatusBadge status={doc.status} />
      {extras.map((badge) => (
        <Badge key={badge.key} tone={badge.tone} title={badge.title}>
          {badge.label}
        </Badge>
      ))}
      {doc.status === 'FAILED' && doc.error_message && (
        <span className="documents-text-danger" style={{ fontSize: 'var(--text-xs)' }} title={explainFailure(doc.error_message)}>
          ⚠ {explainFailure(doc.error_message).split('.')[0]}
        </span>
      )}
    </div>
  )
}
