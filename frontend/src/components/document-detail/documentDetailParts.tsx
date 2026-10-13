import { useState, type CSSProperties } from 'react'
import { Save, Copy, Check, X } from 'lucide-react'
import type { DocumentLanguage, SecurityLevel } from '../../hooks/useDocumentMetadata'
import { DOCUMENT_LANGUAGE_OPTIONS, documentLanguageLabel } from './documentDetailHelpers'

// 메타정보 편집 컨트롤 공통 모양 — 버튼은 테두리 상자로, 셀렉트는 오른쪽 ▼ 화살표로 "누르는 것"임을 드러낸다.
const CHEVRON_ICON =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path d='M1 1l4 4 4-4' fill='none' stroke='%23475569' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/></svg>\")"

export const EDIT_BUTTON_STYLE: CSSProperties = {
  background: '#fff',
  border: '1px solid #256ef4',
  borderRadius: 4,
  cursor: 'pointer',
  padding: '1px 10px',
  color: '#256ef4',
  fontSize: 12,
  lineHeight: 1.6,
}

const ICON_BUTTON_STYLE: CSSProperties = {
  background: '#fff',
  border: '1px solid #cbd5e1',
  borderRadius: 4,
  cursor: 'pointer',
  padding: 3,
  display: 'inline-flex',
  alignItems: 'center',
}

export const SELECT_STYLE: CSSProperties = {
  fontSize: 12,
  color: '#0f172a',
  border: '1px solid #94a3b8',
  borderRadius: 4,
  padding: '3px 26px 3px 8px',
  backgroundColor: '#fff',
  backgroundImage: CHEVRON_ICON,
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 8px center',
  appearance: 'none',
  WebkitAppearance: 'none',
  cursor: 'pointer',
}


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
  label, value, placeholder = '미입력', onSave, maxLength, allowEmpty = true, viewExtra,
}: {
  label: string
  value: string | null
  placeholder?: string
  onSave: (value: string) => void
  maxLength?: number
  // false면 빈 값 저장을 막는다(제목처럼 값을 지우려면 자동값 복원을 써야 하는 필드).
  allowEmpty?: boolean
  viewExtra?: React.ReactNode
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')
  const isSaveBlocked = !allowEmpty && !draft.trim()

  if (!editing) {
    return (
      <Row label={label}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ color: value ? 'inherit' : 'var(--color-text-muted)' }}>
            {value || placeholder}
          </span>
          <button
            onClick={() => { setDraft(value ?? ''); setEditing(true) }}
            style={EDIT_BUTTON_STYLE}
          >
            편집
          </button>
          {viewExtra}
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
          maxLength={maxLength}
          autoFocus
          style={{ fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4, padding: '2px 8px', width: 160 }}
        />
        <button
          onClick={() => { onSave(allowEmpty ? draft : draft.trim()); setEditing(false) }}
          disabled={isSaveBlocked}
          aria-label={`${label} 저장`}
          type="button"
          style={{ ...ICON_BUTTON_STYLE, cursor: isSaveBlocked ? 'not-allowed' : 'pointer', opacity: isSaveBlocked ? 0.4 : 1 }}
        >
          <Save size={14} />
        </button>
        <button
          onClick={() => setEditing(false)}
          aria-label={`${label} 편집 취소`}
          type="button"
          style={ICON_BUTTON_STYLE}
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
            style={EDIT_BUTTON_STYLE}
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
            style={ICON_BUTTON_STYLE}
          >
            <Save size={14} />
          </button>
          <button
            onClick={() => setEditing(false)}
            aria-label={`${label} 편집 취소`}
            type="button"
            style={ICON_BUTTON_STYLE}
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
        style={SELECT_STYLE}
      >
        <option value="">미입력</option>
        {SECURITY_LEVEL_OPTIONS.map((level) => (
          <option key={level} value={level}>{level}</option>
        ))}
      </select>
    </Row>
  )
}

const AUTO_RESET_HELP = '다음 처리 때 자동 생성됩니다'

// 직접 수정된 필드에만 나타나는 배지와 자동값 복원 버튼(제목/언어/분류 공통).
export function AutoValueControls({ isEdited, onReset }: { isEdited: boolean; onReset: () => void }) {
  if (!isEdited) return null
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      <span className="krds-badge xsmall bg-information">직접 수정됨</span>
      <button
        type="button"
        onClick={onReset}
        className="krds-btn text xsmall"
        style={{ padding: 0, cursor: 'pointer', color: '#256ef4' }}
      >
        자동값으로 되돌리기
      </button>
      <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{AUTO_RESET_HELP}</span>
    </span>
  )
}

export function LanguageMetaField({
  value, isEdited, onSave, onReset,
}: {
  value: string | null
  isEdited: boolean
  onSave: (value: DocumentLanguage) => void
  onReset: () => void
}) {
  const hasValue = !!value
  const isKnown = DOCUMENT_LANGUAGE_OPTIONS.some((option) => option.code === value)
  return (
    <Row label="언어">
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <select
          value={value ?? ''}
          onChange={(e) => onSave(e.target.value as DocumentLanguage)}
          aria-label="언어"
          style={SELECT_STYLE}
        >
          {!hasValue && <option value="" disabled>미판별</option>}
          {hasValue && !isKnown && <option value={value}>{documentLanguageLabel(value)}</option>}
          {DOCUMENT_LANGUAGE_OPTIONS.map((option) => (
            <option key={option.code} value={option.code}>{option.label}</option>
          ))}
        </select>
        <AutoValueControls isEdited={isEdited} onReset={onReset} />
      </span>
    </Row>
  )
}
