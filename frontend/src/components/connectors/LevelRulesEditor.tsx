import { Plus, X } from 'lucide-react'
import { SECURITY_LEVELS, SECURITY_LEVEL_LABELS } from '../../hooks/useAccess'
import type { LevelRule } from '../../hooks/useConnectors'
import type { SecurityLevel } from '../../hooks/useDocumentMetadata'

// 경로 접두어별 보안등급. 가장 긴 접두어가 이기고, 맞는 규칙이 없으면 컬렉션 기본 등급을 쓴다.

interface LevelRulesEditorProps {
  rules: LevelRule[]
  onChange: (rules: LevelRule[]) => void
  disabled?: boolean
}

const INPUT: React.CSSProperties = { fontSize: 13, padding: '4px 8px', border: '1px solid #e2e8f0', borderRadius: 4 }

export default function LevelRulesEditor({ rules, onChange, disabled }: LevelRulesEditorProps) {
  const replaceAt = (index: number, next: LevelRule) => onChange(rules.map((r, i) => (i === index ? next : r)))

  return (
    <fieldset style={{ border: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <legend style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>경로별 보안등급</legend>
      {rules.length === 0 && (
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>규칙이 없으면 모든 파일에 컬렉션 기본 등급이 적용됩니다.</span>
      )}
      {rules.map((rule, index) => (
        <span key={index} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input
            style={{ ...INPUT, flex: 1 }}
            value={rule.prefix}
            placeholder="예: 임원/"
            aria-label={`규칙 ${index + 1} 경로 접두어`}
            disabled={disabled}
            onChange={(e) => replaceAt(index, { ...rule, prefix: e.target.value })}
          />
          <select
            style={INPUT}
            value={rule.level}
            aria-label={`규칙 ${index + 1} 보안등급`}
            disabled={disabled}
            onChange={(e) => replaceAt(index, { ...rule, level: e.target.value as SecurityLevel })}
          >
            {SECURITY_LEVELS.map((level) => <option key={level} value={level}>{SECURITY_LEVEL_LABELS[level]}</option>)}
          </select>
          <button
            type="button"
            className="krds-btn text xsmall icon-btn"
            aria-label={`규칙 ${index + 1} 삭제`}
            disabled={disabled}
            onClick={() => onChange(rules.filter((_, i) => i !== index))}
          >
            <X size={14} />
          </button>
        </span>
      ))}
      <button
        type="button"
        className="krds-btn text xsmall"
        style={{ alignSelf: 'flex-start' }}
        disabled={disabled}
        onClick={() => onChange([...rules, { prefix: '', level: 'Confidential' }])}
      >
        <Plus size={14} /> 규칙 추가
      </button>
    </fieldset>
  )
}
