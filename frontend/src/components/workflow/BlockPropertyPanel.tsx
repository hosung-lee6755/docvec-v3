import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, Trash2 } from 'lucide-react'
import { useBlockTypes, type WorkflowBlock } from '../../hooks/useWorkflows'
import { useEmbeddingModels } from '../../hooks/useCollections'
import { useDictionaryEntries } from '../../hooks/useDictionary'
import { jsonSchemaToConfigFields } from '../../lib/blockConfigSchema'
import { getBlockMeta, type ConfigField } from '../../lib/workflowBlocks'
import { IconButton } from '../ui'
import '../../styles/screens/pipeline.css'

interface BlockPropertyPanelProps {
  block: WorkflowBlock | null
  onChange: (blockId: string, updates: { label?: string; config?: Record<string, unknown> }) => void
  onDelete?: (blockId: string) => void
}

function ConfigFieldInput({
  field, inputId, value, onValueChange,
}: {
  field: ConfigField
  inputId: string
  value: unknown
  onValueChange: (value: unknown) => void
}) {
  if (field.type === 'boolean') {
    const checked = value === undefined ? !!field.default : !!value
    return (
      <div>
        <label className="block-panel__check" htmlFor={inputId}>
          <input
            type="checkbox"
            id={inputId}
            checked={checked}
            onChange={(e) => onValueChange(e.target.checked)}
          />
          {field.label}
        </label>
        {field.help && <div className="block-panel__help" style={{ marginTop: 2 }}>{field.help}</div>}
      </div>
    )
  }

  if (field.type === 'number') {
    return (
      <label className="block-panel__field">
        <span className="block-panel__label">{field.label}</span>
        <input
          type="number"
          className="ds-input ds-input--sm"
          value={value === undefined || value === null ? String(field.default ?? '') : String(value)}
          placeholder={field.placeholder}
          min={field.min}
          max={field.max}
          onChange={(e) => onValueChange(e.target.value === '' ? undefined : Number(e.target.value))}
        />
        {field.help && <span className="block-panel__help">{field.help}</span>}
      </label>
    )
  }

  if (field.type === 'select') {
    return (
      <label className="block-panel__field">
        <span className="block-panel__label">{field.label}</span>
        <select
          className="ds-select ds-select--sm"
          value={value === undefined ? String(field.default ?? '') : String(value)}
          onChange={(e) => onValueChange(e.target.value === '' ? undefined : e.target.value)}
        >
          {field.options?.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
        {field.help && <span className="block-panel__help">{field.help}</span>}
      </label>
    )
  }

  if (field.type === 'list' && field.options) {
    // 고정 선택지가 있는 배열 필드 — 체크박스로 고르게 해 오타를 원천 차단한다.
    const options = field.options
    const selected = Array.isArray(value) ? (value as string[]) : []
    const toggle = (optValue: string, checked: boolean) => {
      const next = checked ? [...selected, optValue] : selected.filter((v) => v !== optValue)
      // 선택지 순서를 유지해 저장 값이 클릭 순서에 따라 달라지지 않게 한다(config_hash 안정).
      const ordered = options.map((o) => o.value).filter((v) => next.includes(v))
      onValueChange(ordered.length ? ordered : undefined)
    }
    return (
      <fieldset className="block-panel__field">
        <legend className="block-panel__label">{field.label}</legend>
        {options.map((opt) => {
          const id = `${inputId}_${opt.value}`
          return (
            <label className="block-panel__check" htmlFor={id} key={opt.value}>
              <input
                type="checkbox"
                id={id}
                checked={selected.includes(opt.value)}
                onChange={(e) => toggle(opt.value, e.target.checked)}
              />
              {opt.label}
            </label>
          )
        })}
        {field.help && <span className="block-panel__help">{field.help}</span>}
      </fieldset>
    )
  }

  if (field.type === 'list') {
    const text = Array.isArray(value) ? value.join(', ') : ''
    return (
      <label className="block-panel__field">
        <span className="block-panel__label">{field.label}</span>
        <input
          className="ds-input ds-input--sm"
          value={text}
          placeholder={field.placeholder}
          onChange={(e) => {
            const items = e.target.value.split(',').map((s) => s.trim()).filter(Boolean)
            onValueChange(items.length ? items : undefined)
          }}
        />
        {field.help && <span className="block-panel__help">{field.help}</span>}
      </label>
    )
  }

  if (field.type === 'textarea') {
    return (
      <label className="block-panel__field">
        <span className="block-panel__label">{field.label}</span>
        <textarea
          className="ds-textarea"
          rows={3}
          value={typeof value === 'string' ? value : ''}
          placeholder={field.placeholder}
          onChange={(e) => onValueChange(e.target.value || undefined)}
        />
        {field.help && <span className="block-panel__help">{field.help}</span>}
      </label>
    )
  }

  // 'text'
  return (
    <label className="block-panel__field">
      <span className="block-panel__label">{field.label}</span>
      <input
        className="ds-input ds-input--sm"
        value={typeof value === 'string' ? value : ''}
        placeholder={field.placeholder}
        onChange={(e) => onValueChange(e.target.value || undefined)}
      />
      {field.help && <span className="block-panel__help">{field.help}</span>}
    </label>
  )
}

export default function BlockPropertyPanel({ block, onChange, onDelete }: BlockPropertyPanelProps) {
  const [configText, setConfigText] = useState('{}')
  const [configError, setConfigError] = useState<string | null>(null)
  const { data: blockTypes } = useBlockTypes()
  const { data: embeddingModels } = useEmbeddingModels()
  const { data: stopwordEntries } = useDictionaryEntries('stopword')

  useEffect(() => {
    setConfigText(JSON.stringify(block?.config ?? {}, null, 2))
    setConfigError(null)
  }, [block?.id, block?.config])

  // 하드코딩된 configFields가 없는 블록(전처리 통합 작업으로 추가된 13종)은
  // 백엔드 config_schema(JSON Schema)를 그 자리에서 ConfigField[]로 변환해
  // 폼을 자동 생성한다 — 워크플로우 에디터 팔레트/폼 재편(통합 설계서 §5).
  const schemaFields = useMemo(() => {
    if (!block) return []
    const info = blockTypes?.items.find((i) => i.block_type === block.block_type)
    const fields = info ? jsonSchemaToConfigFields(info.config_schema, block.block_type) : []
    // RAG 저장의 임베딩 모델은 컬렉션 생성 화면과 동일한 실제 사용 가능 모델
    // 목록으로 골라야 한다 — 자유 입력을 허용하면 존재하지 않는 모델 키를 적어
    // 실행 시점에야 실패하는 것을 막는다.
    if (block.block_type === 'rag_store') {
      return fields.map((f) => f.key === 'embedding_model'
        ? {
          ...f,
          type: 'select' as const,
          options: [
            { value: '', label: '컬렉션 기본값 사용' },
            ...(embeddingModels?.items ?? []).map((m) => ({ value: m.key, label: m.label })),
          ],
        }
        : f)
    }
    // 불용어 적용 범위는 사전에 실제 등록된 범위 값 중에서 고른다(오타로 아무 항목에도
    // 매치되지 않는 필터가 만들어지는 것을 막는다).
    if (block.block_type === 'stopword') {
      const scopes = Array.from(new Set((stopwordEntries?.items ?? []).flatMap((e) => e.scope ?? []))).sort()
      const selected = Array.isArray(block.config?.scope_filter) ? (block.config.scope_filter as string[]) : []
      const values = Array.from(new Set(['ALL', ...scopes, ...selected]))
      return fields.map((f) => f.key === 'scope_filter'
        ? {
          ...f,
          type: 'list' as const,
          options: values.map((v) => ({ value: v, label: v })),
          help: '사전에 등록된 적용 범위 중에서 고릅니다. 아무것도 체크하지 않으면 전체 범위에 적용합니다.',
        }
        : f)
    }
    return fields
  }, [block, blockTypes, embeddingModels, stopwordEntries])

  if (!block) {
    return <div className="block-panel__empty">블록을 선택하면 속성을 편집할 수 있습니다</div>
  }

  const meta = getBlockMeta(block.block_type)
  const Icon = meta.icon
  const configFields = meta.configFields ?? schemaFields

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
    <div className="block-panel">
      <div className="block-panel__head">
        {/* 블록 범주색은 구분용이라 인라인 색을 그대로 쓴다. */}
        <div
          className="block-panel__icon"
          style={{ background: `${meta.color}26`, color: meta.color }}
        >
          <Icon size={16} aria-hidden="true" />
        </div>
        <div className="block-panel__titles">
          <div className="block-panel__name">{meta.label}</div>
          <div className="block-panel__desc">{meta.description}</div>
        </div>
        {onDelete && (
          <IconButton tone="danger" label="블록 삭제" onClick={() => onDelete(block.id)}>
            <Trash2 size={14} aria-hidden="true" />
          </IconButton>
        )}
      </div>

      <label className="block-panel__field">
        <span className="block-panel__label">이름</span>
        <input
          value={block.label ?? ''}
          onChange={(e) => onChange(block.id, { label: e.target.value })}
          placeholder={meta.label}
          className="ds-input ds-input--sm"
        />
      </label>

      {configFields.length > 0 && (
        <div className="block-panel__section">
          <span className="block-panel__label">설정</span>
          {configFields.map((field) => (
            <ConfigFieldInput
              key={field.key}
              field={field}
              inputId={`cfg_${block.id}_${field.key}`}
              value={block.config?.[field.key]}
              onValueChange={(value) => setConfigValue(field.key, value)}
            />
          ))}
        </div>
      )}

      {configFields.length === 0 && (
        <span className="block-panel__help">
          {meta.configHint ?? '이 블록은 별도 설정이 필요 없습니다.'}
        </span>
      )}

      <details className="block-panel__json">
        <summary>고급 설정 (JSON 직접 편집)</summary>
        <div className="block-panel__json-body">
          <textarea
            className="ds-textarea"
            aria-label="고급 설정 JSON"
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
          />
          {configError && (
            <span className="block-panel__error">
              <AlertCircle size={13} aria-hidden="true" /> {configError}
            </span>
          )}
        </div>
      </details>
    </div>
  )
}
