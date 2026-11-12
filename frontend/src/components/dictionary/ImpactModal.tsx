import { useStartPartialReprocess } from '../../hooks/useDocumentRuns'
import { type DictionaryImpact, type DictionaryEntryType } from '../../hooks/useDictionary'
import { Alert, Button, Modal } from '../ui'
import '../../styles/screens/pipeline.css'

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

  const dismiss = () => { onClose(); onReprocessDone(null) }

  return (
    <Modal
      isOpen
      title={`영향 문서 ${impact.affected_document_count}건`}
      onClose={dismiss}
      footer={(
        <>
          <Button variant="secondary" onClick={dismiss}>나중에</Button>
          <Button
            variant="primary"
            onClick={handleReprocessAffected}
            disabled={startPartialReprocess.isPending || reprocessDone !== null}
          >
            {startPartialReprocess.isPending ? '재처리 시작 중…' : `${impact.affected_document_count}건 재처리`}
          </Button>
        </>
      )}
    >
      <div className="pipeline-modal-stack">
        <p className="wf-muted" style={{ fontSize: 'var(--text-sm)' }}>
          이 사전 항목이 이미 적용된 문서입니다. 변경 사항을 반영하려면 재처리가 필요합니다.
        </p>
        <div style={{
          maxHeight: 180, overflowY: 'auto', border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
        }}>
          {impact.documents.map((doc) => (
            <div key={doc.id} style={{
              padding: '6px 10px', fontSize: 'var(--text-xs)', borderBottom: '1px solid var(--color-border-subtle)',
            }}>
              {doc.filename}
            </div>
          ))}
        </div>
        {reprocessDone !== null && (
          <Alert tone="success">{reprocessDone}건 재처리를 시작했습니다.</Alert>
        )}
      </div>
    </Modal>
  )
}
