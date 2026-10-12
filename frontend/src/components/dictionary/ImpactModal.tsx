import { X } from 'lucide-react'
import { useStartPartialReprocess } from '../../hooks/useDocumentRuns'
import { type DictionaryImpact, type DictionaryEntryType } from '../../hooks/useDictionary'

const ENTRY_TYPE_TO_BLOCK_TYPE: Record<DictionaryEntryType, string> = {
  stopword: 'stopword', synonym: 'synonym', custom_word: 'user_dict',
}

interface ImpactModalProps {
  impact: DictionaryImpact | null
  tab: DictionaryEntryType
  reprocessDone: number | null
  onClose: () => void
  onReprocessDone: (done: number | null) => void
}

export function ImpactModal({
  impact,
  tab,
  reprocessDone,
  onClose,
  onReprocessDone,
}: ImpactModalProps) {
  const startPartialReprocess = useStartPartialReprocess()

  const handleReprocessAffected = async () => {
    if (!impact) return
    const blockType = ENTRY_TYPE_TO_BLOCK_TYPE[tab]
    let done = 0
    for (const doc of impact.documents) {
      try {
        await startPartialReprocess.mutateAsync({
          documentId: doc.id,
          startBlockType: blockType,
          reason: '사전 항목 변경에 따른 일괄 재처리',
        })
        done += 1
      } catch {
        // 개별 문서 재처리 실패는 건너뛰고 나머지는 계속 진행
      }
    }
    onReprocessDone(done)
  }

  if (!impact) return null

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
      }}
    >
      <section className="krds-modal fade shown in" role="dialog">
        <div className="modal-dialog modal-sm">
          <div className="modal-content">
            <div className="modal-header">
              <h2 className="modal-title">영향 문서 {impact.affected_document_count}건</h2>
            </div>
            <div className="modal-conts">
              <div className="conts-area" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
                  이 사전 항목이 이미 적용된 문서입니다. 변경 사항을 반영하려면 재처리가 필요합니다.
                </p>
                <div style={{
                  maxHeight: 180, overflowY: 'auto', border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-md)',
                }}>
                  {impact.documents.map((doc) => (
                    <div key={doc.id} style={{ padding: '6px 10px', fontSize: 12, borderBottom: '1px solid #f1f5f9' }}>
                      {doc.filename}
                    </div>
                  ))}
                </div>
                {reprocessDone !== null && (
                  <p style={{ fontSize: 12, color: 'var(--color-success)', margin: 0 }}>
                    {reprocessDone}건 재처리를 시작했습니다.
                  </p>
                )}
                <div className="modal-btn btn-wrap">
                  <button
                    type="button"
                    onClick={() => { onClose(); onReprocessDone(null) }}
                    className="krds-btn medium secondary"
                  >
                    나중에
                  </button>
                  <button
                    type="button"
                    onClick={handleReprocessAffected}
                    disabled={startPartialReprocess.isPending || reprocessDone !== null}
                    className="krds-btn medium primary"
                  >
                    {startPartialReprocess.isPending ? '재처리 시작 중…' : `${impact.affected_document_count}건 재처리`}
                  </button>
                </div>
              </div>
            </div>
            <button
              type="button"
              className="krds-btn medium icon btn-close close-modal"
              onClick={() => { onClose(); onReprocessDone(null) }}
            >
              <span className="sr-only">닫기</span>
              <X size={20} />
            </button>
          </div>
        </div>
        <div className="modal-back"></div>
      </section>
    </div>
  )
}
