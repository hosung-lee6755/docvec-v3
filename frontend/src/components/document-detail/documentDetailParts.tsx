import { useState } from 'react'
import { Save, Copy, Check, X } from 'lucide-react'
import type { SecurityLevel } from '../../hooks/useDocumentMetadata'


// UI Components

export function ViewModeToggle({ showJson, onChange }: { showJson: boolean; onChange: (v: boolean) => void }) {
  return (
    <div style={{ display: 'inline-flex', gap: 4, marginBottom: 'var(--space-3)' }} role="group" aria-label="표시 모드 선택">
      {[{ v: false, label: '텍스트' }, { v: true, label: 'JSON' }].map((opt) => (
        <button
          key={String(opt.v)}
          onClick={() => onChange(opt.v)}
          aria-pressed={showJson === opt.v}
          type="button"
          className={showJson === opt.v ? 'krds-btn primary small' : 'krds-btn secondary small'}
          style={{ cursor: 'pointer' }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

export function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '140px 1fr',
      padding: 'var(--space-3) 0',
      borderBottom: '1px solid var(--color-border)',
    }}>
      <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>{label}</span>
      <span style={{ fontSize: 13, minWidth: 0, overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
        {children}
      </span>
    </div>
  )
}

export function CopyableValue({ value, display }: { value: string; display: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async () => {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ fontFamily: 'monospace', fontSize: 11, overflowWrap: 'anywhere', wordBreak: 'break-all' }}>
        {display}
      </span>
      <button
        onClick={handleCopy}
        title="전체 값 복사"
        className="krds-btn text small"
        style={{ cursor: 'pointer', padding: 2, display: 'inline-flex', alignItems: 'center' }}
      >
        {copied ? <Check size={12} style={{ color: '#16a34a' }} /> : <Copy size={12} />}
      </button>
    </span>
  )
}

export function EditableMetaField({
  label, value, placeholder = '미입력', onSave,
}: { label: string; value: string | null; placeholder?: string; onSave: (value: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')

  if (!editing) {
    return (
      <Row label={label}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: value ? 'inherit' : 'var(--color-text-muted)' }}>
            {value || placeholder}
          </span>
          <button
            onClick={() => { setDraft(value ?? ''); setEditing(true) }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'var(--color-primary)', fontSize: 12 }}
          >
            편집
          </button>
        </span>
      </Row>
    )
  }

  return (
    <Row label={label}>
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoFocus
          style={{ fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4, padding: '2px 8px', width: 160 }}
        />
        <button
          onClick={() => { onSave(draft); setEditing(false) }}
          aria-label={`${label} 저장`}
          type="button"
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex' }}
        >
          <Save size={14} />
        </button>
        <button
          onClick={() => setEditing(false)}
          aria-label={`${label} 편집 취소`}
          type="button"
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex' }}
        >
          <X size={14} />
        </button>
      </span>
    </Row>
  )
}

export function DateMetaField({
  label, value, onSave,
}: { label: string; value: string | null; onSave: (value: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')
  const [error, setError] = useState('')

  const isValidDate = (d: string): boolean => /^\d{4}-\d{2}-\d{2}$/.test(d) && !Number.isNaN(new Date(d).getTime())

  if (!editing) {
    return (
      <Row label={label}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: value ? 'inherit' : 'var(--color-text-muted)' }}>
            {value || '미입력'}
          </span>
          <button
            onClick={() => { setDraft(value ?? ''); setEditing(true); setError('') }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'var(--color-primary)', fontSize: 12 }}
            type="button"
          >
            편집
          </button>
        </span>
      </Row>
    )
  }

  return (
    <Row label={label}>
      <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 4 }}>
        <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <input
            type="date"
            value={draft}
            onChange={(e) => { setDraft(e.target.value); setError('') }}
            placeholder="YYYY-MM-DD"
            autoFocus
            style={{ fontSize: 12, border: `1px solid ${error ? '#dc2626' : '#e2e8f0'}`, borderRadius: 4, padding: '2px 8px', width: 160 }}
          />
          <button
            onClick={() => {
              if (!draft.trim()) {
                onSave('')
                setEditing(false)
              } else if (isValidDate(draft)) {
                onSave(draft)
                setEditing(false)
              } else {
                setError('YYYY-MM-DD 형식으로 입력하세요')
              }
            }}
            aria-label={`${label} 저장`}
            type="button"
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex' }}
          >
            <Save size={14} />
          </button>
          <button
            onClick={() => setEditing(false)}
            aria-label={`${label} 편집 취소`}
            type="button"
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex' }}
          >
            <X size={14} />
          </button>
        </span>
        {error && <span style={{ fontSize: 12, color: '#dc2626' }}>{error}</span>}
      </span>
    </Row>
  )
}

const SECURITY_LEVEL_OPTIONS: SecurityLevel[] = ['Public', 'Internal', 'Confidential']

export function SecurityLevelField({
  value, onSave,
}: { value: string | null; onSave: (value: SecurityLevel | '') => void }) {
  return (
    <Row label="보안 등급">
      <select
        value={value ?? ''}
        onChange={(e) => onSave(e.target.value as SecurityLevel | '')}
        style={{ fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4, padding: '2px 8px' }}
      >
        <option value="">미입력</option>
        {SECURITY_LEVEL_OPTIONS.map((level) => (
          <option key={level} value={level}>{level}</option>
        ))}
      </select>
    </Row>
  )
}
