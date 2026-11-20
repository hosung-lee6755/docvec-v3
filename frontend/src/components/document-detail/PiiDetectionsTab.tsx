import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import {
  useApprovePii, useBulkReviewPii, usePiiDetections, useRejectPii, useRevealAllPii, useRevealPii,
} from '../../hooks/useDocumentStructure'
import { useAuthStore } from '../../store/authStore'
import { ErrorText } from '../ui'
import { PII_TYPE_LABELS } from '../../lib/documentQueues'

const PII_ACTION_LABELS: Record<string, string> = {
  MARK: '표시', MASK: '마스킹', TOKENIZE: '토큰화', REMOVE: '제거', EXCLUDE_EMBEDDING: '임베딩 제외',
}

export default function PiiDetectionsTab({ documentId }: { documentId: string }) {
  const { data, isLoading, isError, error } = usePiiDetections(documentId)
  const approve = useApprovePii()
  const reject = useRejectPii()
  const reveal = useRevealPii()
  const revealAll = useRevealAllPii()
  const bulkReview = useBulkReviewPii()
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin')
  const [revealed, setRevealed] = useState<Record<string, string>>({})

  const handleReveal = (detectionId: string) => {
    if (revealed[detectionId] != null) {
      setRevealed((prev) => {
        const next = { ...prev }
        delete next[detectionId]
        return next
      })
      return
    }
    reveal.mutate({ documentId, detectionId }, {
      onSuccess: (res) => setRevealed((prev) => ({ ...prev, [detectionId]: res.value })),
    })
  }

  const handleRevealAll = () => {
    revealAll.mutate({ documentId }, { onSuccess: (res) => setRevealed(res.values) })
  }

  const handleBulkReview = (shouldApprove: boolean) => {
    const message = shouldApprove
      ? '탐지된 민감정보를 모두 승인합니다. 이미 해제한 항목도 승인으로 바뀝니다. 계속할까요?'
      : '탐지된 민감정보를 모두 해제합니다. 이미 승인한 항목도 해제로 바뀝니다. 계속할까요?'
    if (!window.confirm(message)) return
    bulkReview.mutate({ documentId, approve: shouldApprove })
  }

  if (isError) return <ErrorText error={error} message="민감정보 탐지 결과를 불러오지 못했습니다." />

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  const detections = data?.detections ?? []
  if (!detections.length) {
    return <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>탐지된 민감정보가 없습니다.</p>
  }
  const approvedCount = detections.filter((d) => d.approved_by).length
  const rejectedCount = detections.filter((d) => !d.approved_by && d.rejected).length
  const revealedCount = Object.keys(revealed).length
  const isReviewBusy = approve.isPending || reject.isPending || bulkReview.isPending

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0, marginRight: 'auto' }}>
          탐지 {detections.length}건, 승인 {approvedCount}건, 해제 {rejectedCount}건
        </p>
        <button
          type="button"
          onClick={() => handleBulkReview(true)}
          disabled={isReviewBusy || approvedCount === detections.length}
          className="ds-btn ds-btn--ghost ds-btn--sm"
        >
          전체 승인
        </button>
        <button
          type="button"
          onClick={() => handleBulkReview(false)}
          disabled={isReviewBusy || rejectedCount === detections.length}
          className="ds-btn ds-btn--ghost ds-btn--sm"
        >
          전체 해제
        </button>
        {isAdmin && (
          <>
            <button
              type="button"
              onClick={handleRevealAll}
              disabled={revealAll.isPending}
              className="ds-btn ds-btn--ghost ds-btn--sm"
            >
              {revealAll.isPending ? '여는 중…' : '전체 원문 보기'}
            </button>
            <button
              type="button"
              onClick={() => setRevealed({})}
              disabled={revealedCount === 0}
              className="ds-btn ds-btn--ghost ds-btn--sm"
            >
              전체 숨기기
            </button>
          </>
        )}
      </div>
      {revealAll.isError && <ErrorText error={revealAll.error} message="원문을 한꺼번에 열지 못했습니다." />}
      {bulkReview.isError && <ErrorText error={bulkReview.error} message="일괄 처리하지 못했습니다." />}
      {approve.isError && <ErrorText error={approve.error} message="승인하지 못했습니다." />}
      {reject.isError && <ErrorText error={reject.error} message="반려하지 못했습니다." />}
      {reveal.isError && <ErrorText error={reveal.error} message="원문을 보지 못했습니다." />}
      <div style={{ overflowX: 'auto', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--color-surface-subtle)' }}>
              {[
                '유형', '탐지 값(마스킹)', '위치', '신뢰도', '조치', '승인',
                ...(isAdmin ? ['원문'] : []),
              ].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid var(--color-border)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {detections.map((d) => (
              <tr key={d.id}>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-surface-muted)' }}>{PII_TYPE_LABELS[d.entity_type] ?? d.entity_type}</td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-surface-muted)', fontFamily: 'var(--font-mono)' }}>
                  {d.masked_value ?? '-'}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-surface-muted)', color: 'var(--color-text-muted)' }}>
                  {d.page_number != null ? `${d.page_number}페이지` : '-'}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-surface-muted)' }}>
                  {d.confidence != null ? d.confidence.toFixed(2) : '-'}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-surface-muted)' }}>
                  {PII_ACTION_LABELS[d.action] ?? d.action}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-surface-muted)' }}>
                  {d.approved_by && <span className="ds-badge ds-badge--success">승인됨</span>}
                  {!d.approved_by && d.rejected && <span className="ds-badge ds-badge--neutral">해제됨</span>}
                  {!d.approved_by && !d.rejected && (
                    <span style={{ display: 'flex', gap: 4 }}>
                      <button
                        type="button"
                        onClick={() => approve.mutate({ documentId, detectionId: d.id })}
                        disabled={isReviewBusy}
                        className="ds-btn ds-btn--ghost ds-btn--sm"
                        style={{ cursor: 'pointer' }}
                      >
                        승인
                      </button>
                      <button
                        type="button"
                        onClick={() => reject.mutate({ documentId, detectionId: d.id })}
                        disabled={isReviewBusy}
                        className="ds-btn ds-btn--ghost ds-btn--sm"
                        style={{ cursor: 'pointer' }}
                      >
                        해제
                      </button>
                    </span>
                  )}
                </td>
                {isAdmin && (
                  <td style={{ padding: '6px 10px', borderBottom: '1px solid var(--color-surface-muted)' }}>
                    <button
                      type="button"
                      onClick={() => handleReveal(d.id)}
                      disabled={reveal.isPending}
                      className="ds-btn ds-btn--ghost ds-btn--sm"
                      style={{ cursor: 'pointer' }}
                    >
                      {revealed[d.id] != null ? '숨기기' : '원문 보기'}
                    </button>
                    {revealed[d.id] != null && (
                      <div style={{ marginTop: 4, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-danger)' }}>
                        {revealed[d.id]}
                      </div>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
