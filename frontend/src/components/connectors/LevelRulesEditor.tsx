import { Plus, X } from 'lucide-react'
import { SECURITY_LEVELS, SECURITY_LEVEL_LABELS } from '../../hooks/useAccess'
import type { LevelRule } from '../../hooks/useConnectors'
import type { SecurityLevel } from '../../hooks/useDocumentMetadata'
import { Button, IconButton, Input, Select } from '../ui'

// 경로 접두어별 보안등급. 가장 긴 접두어가 이기고, 맞는 규칙이 없으면 컬렉션 기본 등급을 쓴다.

interface LevelRulesEditorProps {
  rules: LevelRule[]
  onChange: (rules: LevelRule[]) => void
  disabled?: boolean
}

export default function LevelRulesEditor({ rules, onChange, disabled }: LevelRulesEditorProps) {
  const replaceAt = (index: number, next: LevelRule) => onChange(rules.map((r, i) => (i === index ? next : r)))

  return (
    <fieldset style={{ border: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      <legend style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--weight-semibold)', marginBottom: 'var(--space-1)' }}>경로별 보안등급</legend>
      {rules.length === 0 && (
        <span className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)' }}>규칙이 없으면 모든 파일에 컬렉션 기본 등급이 적용됩니다.</span>
      )}
      {rules.map((rule, index) => (
        <span key={index} style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
          <Input
            controlSize="sm"
            style={{ flex: 1, minWidth: 0 }}
            value={rule.prefix}
            placeholder="예: 임원/"
            aria-label={`규칙 ${index + 1} 경로 접두어`}
            disabled={disabled}
            onChange={(e) => replaceAt(index, { ...rule, prefix: e.target.value })}
          />
          <Select
            controlSize="sm"
            value={rule.level}
            style={{ width: 96, flex: "0 0 auto" }}
            aria-label={`규칙 ${index + 1} 보안등급`}
            disabled={disabled}
            onChange={(e) => replaceAt(index, { ...rule, level: e.target.value as SecurityLevel })}
          >
            {SECURITY_LEVELS.map((level) => <option key={level} value={level}>{SECURITY_LEVEL_LABELS[level]}</option>)}
          </Select>
          <IconButton
            label={`규칙 ${index + 1} 삭제`}
            disabled={disabled}
            onClick={() => onChange(rules.filter((_, i) => i !== index))}
          >
            <X size={14} aria-hidden="true" />
          </IconButton>
        </span>
      ))}
      <Button
        variant="ghost"
        size="sm"
        style={{ alignSelf: 'flex-start' }}
        disabled={disabled}
        icon={<Plus size={14} aria-hidden="true" />}
        onClick={() => onChange([...rules, { prefix: '', level: 'Confidential' }])}
      >
        규칙 추가
      </Button>
    </fieldset>
  )
}
