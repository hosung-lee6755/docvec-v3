import { useState } from 'react'
import { X } from 'lucide-react'
import { useWorkflowGraph, useWorkflowVersions } from '../../hooks/useWorkflows'
import { getBlockMeta } from '../../lib/workflowBlocks'

interface VersionCompareModalProps {
  workflowId: string
  workflowName: string
  onClose: () => void
}

function VersionBlockList({ workflowId, versionId }: { workflowId: string; versionId: string | null }) {
  const { data, isLoading } = useWorkflowGraph(workflowId, versionId)
  if (!versionId) return <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>버전을 선택하세요.</p>
  if (isLoading) return <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>불러오는 중...</p>
  const blocks = data?.blocks ?? []
  if (!blocks.length) return <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>블록이 없습니다.</p>
  return (
    <ol style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 6 }}>
      {blocks.map((block) => {
        const meta = getBlockMeta(block.block_type)
        return (
          <li key={block.id} style={{ fontSize: 12.5 }}>
            <span style={{ fontWeight: 600 }}>{block.label || meta.label}</span>
            <span style={{ color: 'var(--color-text-muted)' }}> · {meta.label}</span>
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
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
    }}>
      <div style={{
        background: 'var(--color-surface)', color: 'var(--color-text)', borderRadius: 'var(--radius-md)',
        padding: 'var(--space-5)', width: 640, maxHeight: '80vh', overflowY: 'auto',
        display: 'flex', flexDirection: 'column', gap: 'var(--space-3)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>버전 비교 — {workflowName}</h2>
          <button type="button" onClick={onClose} className="krds-btn text xsmall" style={{ cursor: 'pointer', color: 'var(--color-text)' }}>
            <X size={16} />
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
          <div>
            <select
              className="krds-form-select"
              style={{ width: '100%', marginBottom: 'var(--space-2)' }}
              value={versionA ?? ''}
              onChange={(e) => setVersionA(e.target.value || null)}
            >
              <option value="">버전 선택</option>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>v{v.version_number}{v.published_at ? ' (발행됨)' : ' (초안)'}</option>
              ))}
            </select>
            <VersionBlockList workflowId={workflowId} versionId={versionA} />
          </div>
          <div>
            <select
              className="krds-form-select"
              style={{ width: '100%', marginBottom: 'var(--space-2)' }}
              value={versionB ?? ''}
              onChange={(e) => setVersionB(e.target.value || null)}
            >
              <option value="">버전 선택</option>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>v{v.version_number}{v.published_at ? ' (발행됨)' : ' (초안)'}</option>
              ))}
            </select>
            <VersionBlockList workflowId={workflowId} versionId={versionB} />
          </div>
        </div>
      </div>
    </div>
  )
}
