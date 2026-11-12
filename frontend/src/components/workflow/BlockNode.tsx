import { AlertTriangle } from 'lucide-react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { getBlockMeta } from '../../lib/workflowBlocks'
import '../../styles/screens/pipeline.css'

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

export default function BlockNode({ data, selected }: NodeProps) {
  const { label, blockType, invalid } = data as BlockNodeData
  const meta = getBlockMeta(blockType)
  const Icon = meta.icon
  const nodeClass = [
    'pipeline-node',
    selected && !invalid ? 'pipeline-node--selected' : '',
    invalid ? 'pipeline-node--invalid' : '',
  ].filter(Boolean).join(' ')

  return (
    // 선택된 노드의 테두리 색은 블록 범주색이라 인라인으로 준다.
    <div className={nodeClass} style={selected && !invalid ? { borderColor: meta.color } : undefined}>
      {blockType !== 'input' && (
        <Handle type="target" position={Position.Top} style={handleStyle(meta.color)} />
      )}

      <div className="pipeline-node__head">
        <div className="pipeline-node__icon" style={{ background: `${meta.color}26`, color: meta.color }}>
          <Icon size={15} aria-hidden="true" />
        </div>
        <span className="pipeline-node__label">{label || meta.label}</span>
        {invalid && (
          <span role="img" aria-label="검증 오류">
            <AlertTriangle size={14} color="var(--color-danger)" style={{ flexShrink: 0 }} aria-hidden="true" />
          </span>
        )}
      </div>

      {meta.description && (
        <div className="pipeline-node__desc">{meta.description}</div>
      )}

      {blockType !== 'output' && (
        <Handle type="source" position={Position.Bottom} style={handleStyle(meta.color)} />
      )}
    </div>
  )
}
