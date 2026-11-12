import { useState } from 'react'
import { useWorkflowGraph, useWorkflowVersions } from '../../hooks/useWorkflows'
import { getBlockMeta } from '../../lib/workflowBlocks'
import { Modal, Select } from '../ui'
import '../../styles/screens/pipeline.css'

interface VersionCompareModalProps {
  workflowId: string
  workflowName: string
  onClose: () => void
}

function VersionBlockList({ workflowId, versionId }: { workflowId: string; versionId: string | null }) {
  const { data, isLoading } = useWorkflowGraph(workflowId, versionId)
  if (!versionId) return <p className="wf-muted">버전을 선택하세요.</p>
  if (isLoading) return <p className="wf-muted">불러오는 중...</p>
  const blocks = data?.blocks ?? []
  if (!blocks.length) return <p className="wf-muted">블록이 없습니다.</p>
  return (
    <ol className="wf-compare-list">
      {blocks.map((block) => {
        const meta = getBlockMeta(block.block_type)
        return (
          <li key={block.id}>
            <span style={{ fontWeight: 'var(--weight-semibold)' }}>{block.label || meta.label}</span>
            <span className="wf-compare-list__meta"> · {meta.label}</span>
          </li>
        )
      })}
    </ol>
  )
}

export default function VersionCompareModal({ workflowId, workflowName, onClose }: VersionCompareModalProps) {
  const { data: versionsData } = useWorkflowVersions(workflowId)
  const versions = versionsData?.items ?? []
  const [versionA, setVersionA] = useState<string | null>(versions[1]?.id ?? null)
  const [versionB, setVersionB] = useState<string | null>(versions[0]?.id ?? null)

  return (
    <Modal isOpen title={`버전 비교 — ${workflowName}`} onClose={onClose} size="lg">
      <div className="wf-compare-grid">
        <div>
          <Select
            aria-label="비교 버전 A"
            value={versionA ?? ''}
            onChange={(e) => setVersionA(e.target.value || null)}
          >
            <option value="">버전 선택</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>v{v.version_number}{v.published_at ? ' (발행됨)' : ' (초안)'}</option>
            ))}
          </Select>
          <VersionBlockList workflowId={workflowId} versionId={versionA} />
        </div>
        <div>
          <Select
            aria-label="비교 버전 B"
            value={versionB ?? ''}
            onChange={(e) => setVersionB(e.target.value || null)}
          >
            <option value="">버전 선택</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>v{v.version_number}{v.published_at ? ' (발행됨)' : ' (초안)'}</option>
            ))}
          </Select>
          <VersionBlockList workflowId={workflowId} versionId={versionB} />
        </div>
      </div>
    </Modal>
  )
}
