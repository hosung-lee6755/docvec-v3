import { X, Loader2, Layers } from 'lucide-react'
import { useCollectionVectorStats } from '../hooks/useCollectionVectorStats'

interface VectorStatsModalProps {
  collectionId: string
  collectionName: string
  onClose: () => void
}

const REEMBED_LABELS: Record<string, string> = {
  PENDING: '재임베딩 대기 중',
  RUNNING: '재임베딩 진행 중',
  COMPLETED: '재임베딩 완료',
  FAILED: '재임베딩 일부 실패',
}

export default function VectorStatsModal({ collectionId, collectionName, onClose }: VectorStatsModalProps) {
  const { data, isLoading, isError } = useCollectionVectorStats(collectionId)

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60,
    }}>
      <section className="krds-modal fade shown in" role="dialog">
        <div className="modal-dialog modal-sm">
          <div className="modal-content">
            <div className="modal-header">
              <h2 className="modal-title">벡터 DB 현황 — {collectionName}</h2>
            </div>
            <div className="modal-conts">
              <div className="conts-area">
                {isLoading && (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
                    <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
                  </div>
                )}

                {isError && (
                  <p style={{ color: '#dc2626', fontSize: 13 }}>현황을 불러오지 못했습니다.</p>
                )}

                {data && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                    <StatRow label="임베딩 모델" value={data.embedding_model_label} />
                    <StatRow label="벡터 차원" value={data.dimension ? `${data.dimension}차원` : '-'} />
                    <StatRow
                      label="문서 색인 현황"
                      value={`${data.indexed_documents} / ${data.total_documents}건 색인 완료`}
                    />
                    <StatRow label="실제 저장된 벡터(청크) 수" value={`${data.total_vectors.toLocaleString('en-US')}개`} />
                    {data.reembed_status && (
                      <StatRow
                        label="재임베딩 상태"
                        value={`${REEMBED_LABELS[data.reembed_status] ?? data.reembed_status}${data.reembed_progress ? ` (${data.reembed_progress})` : ''}`}
                        warn={data.reembed_status === 'FAILED'}
                      />
                    )}
                  </div>
                )}
              </div>
            </div>
            <div className="modal-btn btn-wrap">
              <button type="button" onClick={onClose} className="krds-btn medium secondary">닫기</button>
            </div>
            <button type="button" onClick={onClose} className="krds-btn medium icon btn-close">
              <span className="sr-only">닫기</span>
              <X size={20} />
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}

function StatRow({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-3)' }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--color-text-muted)', fontSize: 13 }}>
        <Layers size={14} />
        {label}
      </span>
      <span style={{ fontWeight: 600, color: warn ? '#dc2626' : 'inherit' }}>{value}</span>
    </div>
  )
}
