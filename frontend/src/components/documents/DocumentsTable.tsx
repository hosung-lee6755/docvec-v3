import { ArrowDown, ArrowUp, Trash2 } from 'lucide-react'
import { type Document, type DocumentSortBy, type SortOrder } from '../../hooks/useDocuments'
import { STATUS_BADGE_CLASSES, STATUS_LABELS } from '../../lib/documentStatus'
import { formatLocalDate } from '../../lib/documentLifecycle'

// 통과(SUCCESS)는 배지를 달지 않는다. 눈여겨볼 판정만 보인다.
const QUALITY_BADGES: Record<string, { label: string; className: string }> = {
  SUCCESS_WITH_WARNING: { label: '품질 경고', className: 'bg-warning' },
  REVIEW_REQUIRED: { label: '검토 필요', className: 'bg-warning' },
  PARTIAL_FAILURE: { label: '부분 실패', className: 'bg-danger' },
  FAILURE: { label: '품질 실패', className: 'bg-danger' },
}

// 버전·수명주기 배지. 현재 버전(current)이고 만료일이 없으면 아무것도 달지 않는다.
function lifecycleBadges(doc: Document): { key: string; label: string; className: string; title?: string }[] {
  const badges: { key: string; label: string; className: string; title?: string }[] = []
  if (doc.version_number > 1) {
    badges.push({ key: 'version', label: `v${doc.version_number}`, className: 'bg-information', title: `같은 문서의 ${doc.version_number}번째 버전입니다.` })
  }
  if (doc.lifecycle_state === 'archived') {
    badges.push({ key: 'archived', label: '보관됨', className: 'bg-gray', title: '보관된 문서는 검색과 답변에 쓰이지 않습니다. 문서 상세에서 다시 꺼낼 수 있습니다.' })
  }
  if (doc.lifecycle_state === 'superseded') {
    badges.push({ key: 'superseded', label: '이전 버전', className: 'bg-gray', title: '새 버전이 현재 버전이 되어 검색에서 빠졌습니다. 이력은 문서 상세에서 볼 수 있습니다.' })
  }
  if (doc.lifecycle_state === 'pending') {
    badges.push({ key: 'pending', label: '새 버전 처리 중', className: 'bg-information', title: '새 버전을 처리하는 중입니다. 완료되면 현재 버전이 됩니다.' })
  }
  if (doc.expires_at) {
    badges.push({ key: 'expires', label: `만료 ${formatLocalDate(doc.expires_at)}`, className: 'bg-warning', title: '만료일이 지나면 자동으로 보관됩니다.' })
  }
  return badges
}

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
    <div className="krds-table-wrap">
      <table className="tbl col data" style={{ width: '100%' }}>
        <caption>문서 목록</caption>
        <thead>
          <tr>
            <th scope="col" style={{ width: '5%' }}>
              <div className="krds-form-check">
                <input
                  type="checkbox"
                  className="chk"
                  id="doc_chk_all"
                  checked={selectedIds.size > 0 && selectedIds.size === documents?.length}
                  onChange={onToggleAll}
                />
                <label htmlFor="doc_chk_all"></label>
              </div>
            </th>
            {([
              ['파일명', 'filename'],
              ['컬렉션', null],
              ['크기', 'file_size'],
              ['상태', 'status'],
              ['생성일', 'created_at'],
              ['', null],
            ] as [string, DocumentSortBy | null][]).map(([label, column]) => (
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
            <tr key={doc.id} style={{ background: selectedIds.has(doc.id) ? 'rgba(99,102,241,0.04)' : undefined }}>
              <th scope="row">
                <div className="krds-form-check">
                  <input
                    type="checkbox"
                    className="chk"
                    id={`doc_chk_${doc.id}`}
                    checked={selectedIds.has(doc.id)}
                    onChange={() => onToggleSelect(doc.id)}
                  />
                  <label htmlFor={`doc_chk_${doc.id}`}></label>
                </div>
              </th>
              <td style={{ cursor: 'pointer', color: 'var(--color-accent)' }} onClick={() => onDocumentClick(doc.id)}>
                {doc.original_filename}
              </td>
              <td style={{ color: 'var(--color-text-muted)' }}>
                {doc.collection_id
                  ? (collectionsMap[doc.collection_id] ?? doc.collection_id.slice(0, 8))
                  : '-'}
              </td>
              <td style={{ color: 'var(--color-text-muted)' }}>
                {(doc.file_size / 1024).toFixed(1)} KB
              </td>
              <td>
                <span className={`krds-badge ${STATUS_BADGE_CLASSES[doc.status] ?? 'bg-gray'}`}>
                  {STATUS_LABELS[doc.status] ?? doc.status}
                </span>
                {doc.ocr_used && (
                  <span
                    className="krds-badge xsmall bg-information"
                    style={{ marginLeft: 'var(--space-2)' }}
                    title="스캔 이미지 페이지를 OCR로 인식한 문서입니다."
                  >
                    OCR
                  </span>
                )}
                {QUALITY_BADGES[doc.quality_status ?? ''] && (
                  <span
                    className={`krds-badge xsmall ${QUALITY_BADGES[doc.quality_status ?? ''].className}`}
                    style={{ marginLeft: 'var(--space-2)' }}
                    title="최근 처리의 품질 판정입니다. 문서 상세의 품질 탭에서 이유를 볼 수 있습니다."
                  >
                    {QUALITY_BADGES[doc.quality_status ?? ''].label}
                  </span>
                )}
                {(doc.low_ocr_pages?.length ?? 0) > 0 && (
                  <span
                    className="krds-badge xsmall bg-warning"
                    style={{ marginLeft: 'var(--space-2)' }}
                    title={`OCR 신뢰도가 기준보다 낮은 쪽: ${doc.low_ocr_pages?.join(', ')}`}
                  >
                    OCR 낮음 {doc.low_ocr_pages?.length}쪽
                  </span>
                )}
                {lifecycleBadges(doc).map((badge) => (
                  <span
                    key={badge.key}
                    className={`krds-badge xsmall ${badge.className}`}
                    style={{ marginLeft: 'var(--space-2)' }}
                    title={badge.title}
                  >
                    {badge.label}
                  </span>
                ))}
                {doc.status === 'FAILED' && doc.error_message && (
                  <span style={{ marginLeft: 'var(--space-2)', fontSize: 11, color: 'var(--color-danger)' }} title={doc.error_message}>⚠</span>
                )}
              </td>
              <td style={{ color: 'var(--color-text-muted)' }}>
                {new Date(doc.created_at).toLocaleDateString('ko-KR')}
              </td>
              <td>
                {confirmDeleteId === doc.id ? (
                  <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                    <span style={{ fontSize: 12, color: '#dc2626' }}>삭제하시겠습니까?</span>
                    <button
                      onClick={() => onConfirmDelete(doc.id)}
                      disabled={isDeleting}
                      className="krds-btn xsmall primary"
                    >
                      확인
                    </button>
                    <button onClick={() => onCancelDelete()} className="krds-btn xsmall secondary">
                      취소
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => onDeleteClick(doc.id)}
                    className="krds-btn text xsmall icon-btn danger"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
