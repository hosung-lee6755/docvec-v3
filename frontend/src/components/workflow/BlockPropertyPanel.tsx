import { useEffect, useState } from 'react'
import { AlertCircle } from 'lucide-react'
import type { WorkflowBlock } from '../../hooks/useWorkflows'
import { getBlockMeta } from '../../lib/workflowBlocks'

interface BlockPropertyPanelProps {
  block: WorkflowBlock | null
  onChange: (blockId: string, updates: { label?: string; config?: Record<string, unknown> }) => void
}

const fieldLabelStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: 'var(--color-text-muted)',
  textTransform: 'uppercase', letterSpacing: 0.4,
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
      <div style={{ padding: 'var(--space-4)', fontSize: 13, color: 'var(--color-text-muted)', textAlign: 'center' }}>
        블록을 선택하면 속성을 편집할 수 있습니다
      </div>
    )
  }

  const meta = getBlockMeta(block.block_type)
  const Icon = meta.icon

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)', padding: 'var(--space-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <div style={{
          width: 28, height: 28, borderRadius: 'var(--radius-sm)', flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: `${meta.color}26`, color: meta.color,
        }}>
          <Icon size={16} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text)' }}>{meta.label}</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {meta.description}
          </div>
        </div>
      </div>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        <span style={fieldLabelStyle}>이름</span>
        <input
          value={block.label ?? ''}
          onChange={(e) => onChange(block.id, { label: e.target.value })}
          placeholder={meta.label}
          className="krds-input small"
        />
      </label>

      <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        <span style={fieldLabelStyle}>설정 (JSON)</span>
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
          className="krds-input small"
          style={{ fontFamily: 'monospace', fontSize: 12, resize: 'vertical' }}
        />
        {configError && (
          <span style={{
            display: 'flex', alignItems: 'center', gap: 'var(--space-1)',
            color: 'var(--color-danger)', fontSize: 12,
          }}>
            <AlertCircle size={13} /> {configError}
          </span>
        )}
      </label>
    </div>
  )
}
