import { useMemo } from 'react'
import {
  ReactFlow, Background, BackgroundVariant, Controls, MiniMap,
  type Node, type Edge, type Connection, type NodeChange, type NodeMouseHandler,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { WorkflowBlock, WorkflowEdge } from '../../hooks/useWorkflows'
import BlockNode from './BlockNode'
import { getBlockMeta } from '../../lib/workflowBlocks'

const nodeTypes = { blockNode: BlockNode }

interface WorkflowCanvasProps {
  blocks: WorkflowBlock[]
  edges: WorkflowEdge[]
  selectedBlockId: string | null
  onSelectBlock: (blockId: string | null) => void
  onMoveBlock: (blockId: string, position: { x: number; y: number }) => void
  onConnect: (fromBlockId: string, toBlockId: string) => void
  onDeleteBlock: (blockId: string) => void
  onDeleteEdge: (edgeId: string) => void
}

export default function WorkflowCanvas({
  blocks, edges, selectedBlockId, onSelectBlock, onMoveBlock, onConnect, onDeleteBlock, onDeleteEdge,
}: WorkflowCanvasProps) {
  const nodes: Node[] = useMemo(() => blocks.map((block) => ({
    id: block.id,
    type: 'blockNode',
    position: 'x' in block.position ? (block.position as { x: number; y: number }) : { x: 0, y: 0 },
    data: { label: block.label ?? '', blockType: block.block_type },
    selected: block.id === selectedBlockId,
  })), [blocks, selectedBlockId])

  const flowEdges: Edge[] = useMemo(() => edges.map((edge) => {
    const sourceBlock = blocks.find((b) => b.id === edge.from_block_id)
    const color = sourceBlock ? getBlockMeta(sourceBlock.block_type).color : 'var(--color-text-muted)'
    return {
      id: edge.id,
      source: edge.from_block_id,
      target: edge.to_block_id,
      label: edge.condition ? '조건부' : undefined,
      labelStyle: { fill: 'var(--color-text)', fontSize: 11 },
      labelBgStyle: { fill: 'var(--color-surface)' },
      style: { stroke: color, strokeWidth: 2 },
    }
  }), [edges, blocks])

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

  const handleDelete = ({ nodes: removedNodes, edges: removedEdges }: { nodes: Node[]; edges: Edge[] }) => {
    removedNodes.forEach((node) => onDeleteBlock(node.id))
    removedEdges.forEach((edge) => onDeleteEdge(edge.id))
  }

  return (
    <div
      style={{
        width: '100%', height: '100%', background: 'var(--color-bg)',
        '--xy-controls-button-background-color': 'var(--color-surface)',
        '--xy-controls-button-background-color-hover': 'var(--color-border)',
        '--xy-controls-button-color': 'var(--color-text)',
        '--xy-controls-button-color-hover': 'var(--color-text)',
        '--xy-controls-button-border-color': 'var(--color-border)',
        '--xy-minimap-background-color': 'var(--color-surface)',
        '--xy-attribution-background-color': 'transparent',
      } as React.CSSProperties}
    >
      <ReactFlow
        nodes={nodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodesChange={handleNodesChange}
        onConnect={handleConnect}
        onNodeClick={handleNodeClick}
        onPaneClick={() => onSelectBlock(null)}
        onDelete={handleDelete}
        deleteKeyCode={['Backspace', 'Delete']}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.5} color="var(--color-border)" />
        <Controls showInteractive={false} />
        <MiniMap
          pannable zoomable
          maskColor="rgba(15, 23, 42, 0.7)"
          nodeColor={(node) => getBlockMeta((node.data as { blockType?: string })?.blockType ?? '').color}
        />
      </ReactFlow>
    </div>
  )
}
