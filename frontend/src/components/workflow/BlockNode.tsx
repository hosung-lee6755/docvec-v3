import { AlertTriangle } from 'lucide-react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { getBlockMeta } from '../../lib/workflowBlocks'

export interface BlockNodeData {
  label: string
  blockType: string
  // 저장 시 서버 유효성 검사에서 이 블록을 지목한 에러가 있으면 true
  // (워크플로우 에디터 팔레트/폼 재편, 통합 설계서 §5).
  invalid?: boolean
  [key: string]: unknown
}

const handleStyle = (color: string) => ({
  width: 10, height: 10, background: color, border: '2px solid var(--color-surface)',
})

const INVALID_COLOR = '#dc2626'

export default function BlockNode({ data, selected }: NodeProps) {
  const { label, blockType, invalid } = data as BlockNodeData
  const meta = getBlockMeta(blockType)
  const Icon = meta.icon
  const borderColor = invalid ? INVALID_COLOR : selected ? meta.color : 'var(--color-border)'

  return (
    <div
      style={{
        minWidth: 180,
        borderRadius: 'var(--radius-lg)',
        background: 'var(--color-surface)',
        border: `1px solid ${borderColor}`,
        boxShadow: invalid
          ? `0 0 0 2px ${INVALID_COLOR}55, 0 4px 12px rgba(0,0,0,0.35)`
          : selected ? `0 0 0 2px ${meta.color}55, 0 4px 12px rgba(0,0,0,0.35)` : '0 2px 6px rgba(0,0,0,0.25)',
        transition: 'border-color var(--duration-fast), box-shadow var(--duration-fast)',
      }}
    >
      {blockType !== 'input' && (
        <Handle type="target" position={Position.Top} style={handleStyle(meta.color)} />
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', padding: 'var(--space-2) var(--space-3)' }}>
        <div style={{
          width: 26, height: 26, borderRadius: 'var(--radius-sm)', flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: `${meta.color}26`, color: meta.color,
        }}>
          <Icon size={15} />
        </div>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text)', flex: 1 }}>
          {label || meta.label}
        </span>
        {invalid && <AlertTriangle size={14} color={INVALID_COLOR} style={{ flexShrink: 0 }} />}
      </div>

      {meta.description && (
        <div style={{
          padding: '0 var(--space-3) var(--space-2)', fontSize: 11,
          color: 'var(--color-text-muted)', lineHeight: 1.4,
        }}>
          {meta.description}
        </div>
      )}

      {blockType !== 'output' && (
        <Handle type="source" position={Position.Bottom} style={handleStyle(meta.color)} />
      )}
    </div>
  )
}
