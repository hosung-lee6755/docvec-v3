import { useEffect, useState } from 'react'
import type { WorkflowBlock } from '../../hooks/useWorkflows'

interface BlockPropertyPanelProps {
  block: WorkflowBlock | null
  onChange: (blockId: string, updates: { label?: string; config?: Record<string, unknown> }) => void
}

export default function BlockPropertyPanel({ block, onChange }: BlockPropertyPanelProps) {
  const [configText, setConfigText] = useState('{}')
  const [configError, setConfigError] = useState<string | null>(null)

  useEffect(() => {
    setConfigText(JSON.stringify(block?.config ?? {}, null, 2))
    setConfigError(null)
  }, [block?.id])

  if (!block) {
    return (
      <div style={{ padding: 'var(--space-3)', fontSize: 13, color: 'var(--color-text-muted)' }}>
        블록을 선택하면 속성을 편집할 수 있습니다
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', padding: 'var(--space-3)' }}>
      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-muted)' }}>블록 속성</span>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)', fontSize: 13 }}>
        이름
        <input
          value={block.label ?? ''}
          onChange={(e) => onChange(block.id, { label: e.target.value })}
          style={{ padding: 'var(--space-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)' }}
        />
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)', fontSize: 13 }}>
        설정 (JSON)
        <textarea
          value={configText}
          onChange={(e) => setConfigText(e.target.value)}
          onBlur={() => {
            try {
              const parsed = JSON.parse(configText)
              setConfigError(null)
              onChange(block.id, { config: parsed })
            } catch {
              setConfigError('올바른 JSON 형식이 아닙니다')
            }
          }}
          rows={10}
          style={{
            padding: 'var(--space-2)', border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)', fontFamily: 'monospace', fontSize: 12,
          }}
        />
        {configError && <span style={{ color: 'var(--color-danger, #dc2626)' }}>{configError}</span>}
      </label>
    </div>
  )
}
