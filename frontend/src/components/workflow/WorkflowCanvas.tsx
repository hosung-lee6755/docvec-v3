import { useMemo } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  type Node, type Edge, type Connection, type NodeChange, type NodeMouseHandler,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { WorkflowBlock, WorkflowEdge } from '../../hooks/useWorkflows'

const BLOCK_LABELS: Record<string, string> = {
  input: '입력', preprocess: '전처리', classify: '분류',
  extract_entities: '개체 추출', extract_keywords: '키워드 추출', summarize: '요약',
  validate: '검증', branch: '조건 분기', merge: '병합', postprocess: '후처리', output: '출력',
}

interface WorkflowCanvasProps {
  blocks: WorkflowBlock[]
  edges: WorkflowEdge[]
  selectedBlockId: string | null
  onSelectBlock: (blockId: string | null) => void
  onMoveBlock: (blockId: string, position: { x: number; y: number }) => void
  onConnect: (fromBlockId: string, toBlockId: string) => void
}

export default function WorkflowCanvas({
  blocks, edges, selectedBlockId, onSelectBlock, onMoveBlock, onConnect,
}: WorkflowCanvasProps) {
  const nodes: Node[] = useMemo(() => blocks.map((block) => ({
    id: block.id,
    position: 'x' in block.position ? (block.position as { x: number; y: number }) : { x: 0, y: 0 },
    data: { label: block.label || BLOCK_LABELS[block.block_type] || block.block_type },
    selected: block.id === selectedBlockId,
  })), [blocks, selectedBlockId])

  const flowEdges: Edge[] = useMemo(() => edges.map((edge) => ({
    id: edge.id,
    source: edge.from_block_id,
    target: edge.to_block_id,
    label: edge.condition ? '조건부' : undefined,
  })), [edges])

  const handleNodesChange = (changes: NodeChange[]) => {
    for (const change of changes) {
      if (change.type === 'position' && change.position) {
        onMoveBlock(change.id, change.position)
      }
    }
  }

  const handleConnect = (connection: Connection) => {
    if (connection.source && connection.target) {
      onConnect(connection.source, connection.target)
    }
  }

  const handleNodeClick: NodeMouseHandler = (_event, node) => {
    onSelectBlock(node.id)
  }

  return (
    <div style={{ width: '100%', height: '100%' }}>
      <ReactFlow
        nodes={nodes}
        edges={flowEdges}
        onNodesChange={handleNodesChange}
        onConnect={handleConnect}
        onNodeClick={handleNodeClick}
        onPaneClick={() => onSelectBlock(null)}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  )
}
