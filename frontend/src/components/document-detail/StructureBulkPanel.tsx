import { useState } from 'react'
import { ErrorText } from '../ui'

interface StructureBulkPanelProps {
  count: number
  nodeTypes: string[]
  nodeTypeLabels: Record<string, string>
  isPending: boolean
  error: unknown
  onClear: () => void
  onApply: (changes: { nodeType?: string; level?: number }) => void
}

const KEEP = ''

/** 구조 목록에서 체크한 노드들의 유형이나 제목 레벨을 한 번에 바꾼다. */
export default function StructureBulkPanel({
  count, nodeTypes, nodeTypeLabels, isPending, error, onClear, onApply,
}: StructureBulkPanelProps) {
  const [nodeType, setNodeType] = useState(KEEP)
  const [level, setLevel] = useState('')
  const hasChange = nodeType !== KEEP || level.trim() !== ''

  return (
    <section
      aria-label="선택한 노드 한꺼번에 수정"
      style={{
        border: '1px solid var(--color-accent)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
        display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', background: 'var(--color-primary-subtle)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
        <strong style={{ flex: 1 }}>노드 {count}개 선택됨</strong>
        <button type="button" className="ds-btn ds-btn--ghost ds-btn--sm" onClick={onClear} disabled={isPending}>
          선택 해제
        </button>
      </div>
      <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          노드 유형
          <select className="ds-select" value={nodeType} onChange={(e) => setNodeType(e.target.value)} style={{ marginLeft: 6, fontSize: 12 }}>
            <option value={KEEP}>바꾸지 않음</option>
            {nodeTypes.map((t) => <option key={t} value={t}>{nodeTypeLabels[t] ?? t}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          제목 레벨
          <input
            type="number"
            min={0}
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            placeholder="바꾸지 않음"
            style={{ marginLeft: 6, width: 90, fontSize: 12, border: '1px solid var(--color-border)', borderRadius: 4, padding: '2px 6px' }}
          />
        </label>
        <button
          type="button"
          className="ds-btn ds-btn--primary ds-btn--sm"
          disabled={!hasChange || isPending}
          onClick={() => onApply({
            nodeType: nodeType !== KEEP ? nodeType : undefined,
            level: level.trim() ? Number(level) : undefined,
          })}
        >
          선택한 {count}개에 적용
        </button>
      </div>
      {!!error && <ErrorText error={error} message="선택한 노드를 고치지 못했습니다." />}
    </section>
  )
}
