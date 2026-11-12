import { Layers } from 'lucide-react'
import { useCollectionVectorStats } from '../hooks/useCollectionVectorStats'
import { Alert, Button, DescriptionList, Modal, Spinner } from './ui'
import type { DescriptionItem } from './ui'
import '../styles/screens/documents.css'

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

  const footer = <Button variant="secondary" onClick={onClose}>닫기</Button>

  return (
    <Modal isOpen title={`벡터 DB 현황 — ${collectionName}`} onClose={onClose} footer={footer}>
      {isLoading && (
        <div className="documents-center"><Spinner /></div>
      )}

      {isError && (
        <Alert tone="danger">현황을 불러오지 못했습니다.</Alert>
      )}

      {data && <DescriptionList items={buildItems(data)} />}
    </Modal>
  )
}

interface VectorStatsData {
  embedding_model_label: string
  dimension: number | null
  indexed_documents: number
  total_documents: number
  total_vectors: number
  reembed_status?: string | null
  reembed_progress?: string | null
}

function buildItems(data: VectorStatsData): DescriptionItem[] {
  const items: DescriptionItem[] = [
    { key: 'model', term: <Term>임베딩 모델</Term>, detail: data.embedding_model_label },
    { key: 'dimension', term: <Term>벡터 차원</Term>, detail: data.dimension ? `${data.dimension}차원` : '-' },
    {
      key: 'indexed',
      term: <Term>문서 색인 현황</Term>,
      detail: `${data.indexed_documents} / ${data.total_documents}건 색인 완료`,
    },
    {
      key: 'vectors',
      term: <Term>실제 저장된 벡터(청크) 수</Term>,
      detail: `${data.total_vectors.toLocaleString('en-US')}개`,
    },
  ]
  if (data.reembed_status) {
    const label = `${REEMBED_LABELS[data.reembed_status] ?? data.reembed_status}${data.reembed_progress ? ` (${data.reembed_progress})` : ''}`
    items.push({
      key: 'reembed',
      term: <Term>재임베딩 상태</Term>,
      detail: <span className={data.reembed_status === 'FAILED' ? 'documents-text-danger' : undefined}>{label}</span>,
    })
  }
  return items
}

function Term({ children }: { children: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
      <Layers size={14} aria-hidden="true" />
      {children}
    </span>
  )
}
