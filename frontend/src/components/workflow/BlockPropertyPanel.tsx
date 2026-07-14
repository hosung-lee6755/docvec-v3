import { useEffect, useState } from 'react'
import { AlertCircle, Trash2 } from 'lucide-react'
import type { WorkflowBlock } from '../../hooks/useWorkflows'
import { getBlockMeta, type ConfigField } from '../../lib/workflowBlocks'

interface BlockPropertyPanelProps {
  block: WorkflowBlock | null
  onChange: (blockId: string, updates: { label?: string; config?: Record<string, unknown> }) => void
  onDelete?: (blockId: string) => void
}

const fieldLabelStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 700, color: 'var(--color-text-muted)',
  textTransform: 'uppercase', letterSpacing: 0.4,
}

const helpStyle: React.CSSProperties = {
  fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.5,
}

function ConfigFieldInput({
  field, value, onValueChange,
}: {
  field: ConfigField
  value: unknown
  onValueChange: (value: unknown) => void
}) {
  if (field.type === 'boolean') {
    const checked = value === undefined ? !!field.default : !!value
    return (
      <label style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-2)', cursor: 'pointer' }}>
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onValueChange(e.target.checked)}
          style={{ marginTop: 2, flexShrink: 0 }}
        />
        <span style={{ minWidth: 0 }}>
          <span style={{ fontSize: 13, color: 'var(--color-text)' }}>{field.label}</span>
          {field.help && <div style={helpStyle}>{field.help}</div>}
        </span>
      </label>
    )
  }

  if (field.type === 'number') {
    return (
      <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        <span style={fieldLabelStyle}>{field.label}</span>
        <input
          type="number"
          className="krds-input small"
          value={value === undefined || value === null ? String(field.default ?? '') : String(value)}
          min={field.min}
          max={field.max}
          onChange={(e) => onValueChange(e.target.value === '' ? undefined : Number(e.target.value))}
        />
        {field.help && <span style={helpStyle}>{field.help}</span>}
      </label>
    )
  }

  if (field.type === 'select') {
    return (
      <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        <span style={fieldLabelStyle}>{field.label}</span>
        <select
          className="krds-form-select small"
          value={value === undefined ? String(field.default ?? '') : String(value)}
          onChange={(e) => onValueChange(e.target.value)}
        >
          {field.options?.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
        {field.help && <span style={helpStyle}>{field.help}</span>}
      </label>
    )
  }

  if (field.type === 'list') {
    const text = Array.isArray(value) ? value.join(', ') : ''
    return (
      <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        <span style={fieldLabelStyle}>{field.label}</span>
        <input
          className="krds-input small"
          value={text}
          placeholder={field.placeholder}
          onChange={(e) => {
            const items = e.target.value.split(',').map((s) => s.trim()).filter(Boolean)
            onValueChange(items.length ? items : undefined)
          }}
        />
        {field.help && <span style={helpStyle}>{field.help}</span>}
      </label>
    )
  }

  if (field.type === 'textarea') {
    return (
      <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        <span style={fieldLabelStyle}>{field.label}</span>
        <textarea
          className="krds-input small"
          rows={3}
          value={typeof value === 'string' ? value : ''}
          placeholder={field.placeholder}
          onChange={(e) => onValueChange(e.target.value || undefined)}
          style={{ resize: 'vertical' }}
        />
        {field.help && <span style={helpStyle}>{field.help}</span>}
      </label>
    )
  }

  // 'text'
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
      <span style={fieldLabelStyle}>{field.label}</span>
      <input
        className="krds-input small"
        value={typeof value === 'string' ? value : ''}
        placeholder={field.placeholder}
        onChange={(e) => onValueChange(e.target.value || undefined)}
      />
      {field.help && <span style={helpStyle}>{field.help}</span>}
    </label>
  )
}

export default function BlockPropertyPanel({ block, onChange, onDelete }: BlockPropertyPanelProps) {
  const [configText, setConfigText] = useState('{}')
  const [configError, setConfigError] = useState<string | null>(null)

  useEffect(() => {
    setConfigText(JSON.stringify(block?.config ?? {}, null, 2))
    setConfigError(null)
  }, [block?.id, block?.config])

  if (!block) {
    return (
      <div style={{ padding: 'var(--space-4)', fontSize: 13, color: 'var(--color-text-muted)', textAlign: 'center' }}>
        블록을 선택하면 속성을 편집할 수 있습니다
      </div>
    )
  }

  const meta = getBlockMeta(block.block_type)
  const Icon = meta.icon
  const configFields = meta.configFields ?? []

  const setConfigValue = (key: string, value: unknown) => {
    const next: Record<string, unknown> = { ...block.config }
    if (value === undefined) {
      delete next[key]
    } else {
      next[key] = value
    }
    onChange(block.id, { config: next })
  }

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
        <div style={{ minWidth: 0, flex: '1 1 auto' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-text)' }}>{meta.label}</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {meta.description}
          </div>
        </div>
        {onDelete && (
          <button
            type="button"
            onClick={() => onDelete(block.id)}
            title="블록 삭제"
            aria-label="블록 삭제"
            style={{
              flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 26, height: 26, borderRadius: 'var(--radius-sm)', border: 'none',
              background: 'transparent', color: 'var(--color-text-muted)', cursor: 'pointer',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(239,68,68,0.15)'; e.currentTarget.style.color = 'var(--color-danger)' }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--color-text-muted)' }}
          >
            <Trash2 size={14} />
          </button>
        )}
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

      {configFields.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <span style={fieldLabelStyle}>설정</span>
          {configFields.map((field) => (
            <ConfigFieldInput
              key={field.key}
              field={field}
              value={block.config?.[field.key]}
              onValueChange={(value) => setConfigValue(field.key, value)}
            />
          ))}
        </div>
      )}

      {configFields.length === 0 && (
        <span style={helpStyle}>
          {meta.configHint ?? '이 블록은 별도 설정이 필요 없습니다.'}
        </span>
      )}

      <details>
        <summary style={{ fontSize: 11, color: 'var(--color-text-muted)', cursor: 'pointer', userSelect: 'none' }}>
          고급 설정 (JSON 직접 편집)
        </summary>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)', marginTop: 'var(--space-2)' }}>
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
            rows={8}
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
        </div>
      </details>
    </div>
  )
}
