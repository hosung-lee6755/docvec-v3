import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useApprovePii, usePiiDetections, useRejectPii, useRevealPii } from '../../hooks/useDocumentStructure'
import { useAuthStore } from '../../store/authStore'

const PII_ACTION_LABELS: Record<string, string> = {
  MARK: '표시', MASK: '마스킹', TOKENIZE: '토큰화', REMOVE: '제거', EXCLUDE_EMBEDDING: '임베딩 제외',
}

export default function PiiDetectionsTab({ documentId }: { documentId: string }) {
  const { data, isLoading } = usePiiDetections(documentId)
  const approve = useApprovePii()
  const reject = useRejectPii()
  const reveal = useRevealPii()
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>탐지 {detections.length}건</p>
      <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: '#f8fafc' }}>
              {[
                '유형', '탐지 값(마스킹)', '위치', '신뢰도', '조치', '승인',
                ...(isAdmin ? ['원문'] : []),
              ].map((h) => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid #e2e8f0' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {detections.map((d) => (
              <tr key={d.id}>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>{d.entity_type}</td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9', fontFamily: 'monospace' }}>
                  {d.masked_value ?? '-'}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9', color: 'var(--color-text-muted)' }}>
                  {d.page_number != null ? `${d.page_number}페이지` : '-'}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>
                  {d.confidence != null ? d.confidence.toFixed(2) : '-'}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>
                  {PII_ACTION_LABELS[d.action] ?? d.action}
                </td>
                <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>
                  {d.approved_by && <span className="krds-badge xsmall bg-success">승인됨</span>}
                  {!d.approved_by && d.rejected && <span className="krds-badge xsmall bg-gray">해제됨</span>}
                  {!d.approved_by && !d.rejected && (
                    <span style={{ display: 'flex', gap: 4 }}>
                      <button
                        type="button"
                        onClick={() => approve.mutate({ documentId, detectionId: d.id })}
                        disabled={approve.isPending || reject.isPending}
                        className="krds-btn text xsmall"
                        style={{ cursor: 'pointer' }}
                      >
                        승인
                      </button>
                      <button
                        type="button"
                        onClick={() => reject.mutate({ documentId, detectionId: d.id })}
                        disabled={approve.isPending || reject.isPending}
                        className="krds-btn text xsmall"
                        style={{ cursor: 'pointer' }}
                      >
                        해제
                      </button>
                    </span>
                  )}
                </td>
                {isAdmin && (
                  <td style={{ padding: '6px 10px', borderBottom: '1px solid #f1f5f9' }}>
                    <button
                      type="button"
                      onClick={() => handleReveal(d.id)}
                      disabled={reveal.isPending}
                      className="krds-btn text xsmall"
                      style={{ cursor: 'pointer' }}
                    >
                      {revealed[d.id] != null ? '숨기기' : '원문 보기'}
                    </button>
                    {revealed[d.id] != null && (
                      <div style={{ marginTop: 4, fontFamily: 'monospace', fontSize: 11, color: '#dc2626' }}>
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
