import { useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import {
  useDocumentNodes, useUpdateDocumentNode, type DocumentNodeItem,
} from '../../hooks/useDocumentStructure'

const NODE_TYPES = [
  'DOCUMENT', 'COVER', 'TOC', 'SECTION', 'HEADING', 'PARAGRAPH', 'SENTENCE',
  'LIST', 'LIST_ITEM', 'TABLE', 'TABLE_ROW', 'TABLE_CELL', 'IMAGE', 'CAPTION',
  'FOOTNOTE', 'HEADER', 'FOOTER', 'PAGE_NUMBER', 'FORM_FIELD',
]

const NODE_TYPE_LABELS: Record<string, string> = {
  DOCUMENT: '문서', COVER: '표지', TOC: '목차', SECTION: '섹션', HEADING: '제목',
  PARAGRAPH: '문단', SENTENCE: '문장', LIST: '목록', LIST_ITEM: '목록 항목',
  TABLE: '표', TABLE_ROW: '표 행', TABLE_CELL: '표 셀', IMAGE: '그림', CAPTION: '캡션',
  FOOTNOTE: '각주', HEADER: '머리말', FOOTER: '꼬리말', PAGE_NUMBER: '쪽 번호', FORM_FIELD: '양식 필드',
}

const NODE_TYPE_ICONS: Record<string, string> = {
  HEADING: 'H', SECTION: 'H', PARAGRAPH: '¶', SENTENCE: '¶',
  TABLE: '▦', TABLE_ROW: '▦', TABLE_CELL: '▦',
  LIST: '☰', LIST_ITEM: '☰', IMAGE: '🖼',
}

interface TreeNode extends DocumentNodeItem {
  children: TreeNode[]
}

function buildTree(nodes: DocumentNodeItem[]): TreeNode[] {
  const byId = new Map<string, TreeNode>(nodes.map((n) => [n.id, { ...n, children: [] }]))
  const roots: TreeNode[] = []
  for (const node of byId.values()) {
    const parent = node.parent_node_id ? byId.get(node.parent_node_id) : null
    if (parent) parent.children.push(node)
    else roots.push(node)
  }
  return roots
}

function TreeRow({
  node, depth, selectedId, onSelect,
}: { node: TreeNode; depth: number; selectedId: string | null; onSelect: (n: TreeNode) => void }) {
  return (
    <div>
      <button
        type="button"
        onClick={() => onSelect(node)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6, width: '100%', textAlign: 'left',
          padding: '4px 8px', paddingLeft: 8 + depth * 16, fontSize: 12, border: 'none',
          background: node.id === selectedId ? '#eff6ff' : 'transparent', cursor: 'pointer',
          color: node.id === selectedId ? 'var(--color-accent)' : 'inherit',
        }}
      >
        <span style={{ color: '#94a3b8', flexShrink: 0 }}>{NODE_TYPE_ICONS[node.node_type] ?? '·'}</span>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.text?.slice(0, 60) || NODE_TYPE_LABELS[node.node_type] || node.node_type}
        </span>
        {node.user_corrected && <span style={{ flexShrink: 0, color: '#2563eb', fontSize: 11 }}>●</span>}
      </button>
      {node.children.map((child) => (
        <TreeRow key={child.id} node={child} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} />
      ))}
    </div>
  )
}

export default function StructureTab({ documentId }: { documentId: string }) {
  const { data, isLoading } = useDocumentNodes(documentId)
  const updateNode = useUpdateDocumentNode()
  const [selected, setSelected] = useState<DocumentNodeItem | null>(null)
  const [levelInput, setLevelInput] = useState('')
  const [typeInput, setTypeInput] = useState('')

  const nodes = data?.nodes ?? []
  const tree = useMemo(() => buildTree(nodes), [nodes])

  const handleSelect = (node: DocumentNodeItem) => {
    setSelected(node)
    setLevelInput(node.level != null ? String(node.level) : '')
    setTypeInput(node.node_type)
  }

  const handleSave = () => {
    if (!selected) return
    updateNode.mutate({
      documentId,
      nodeId: selected.id,
      level: levelInput.trim() ? Number(levelInput) : undefined,
      nodeType: typeInput !== selected.node_type ? typeInput : undefined,
    })
  }

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  if (!nodes.length) {
    return <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>구조 분석 결과가 없습니다.</p>
  }

  const counts = nodes.reduce<Record<string, number>>((acc, n) => {
    acc[n.node_type] = (acc[n.node_type] ?? 0) + 1
    return acc
  }, {})
  const correctedCount = nodes.filter((n) => n.user_corrected).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 'var(--space-3)' }}>
      <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '260px 1fr', gap: 'var(--space-4)' }}>
        <div style={{ overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)' }}>
          {tree.map((root) => (
            <TreeRow key={root.id} node={root} depth={0} selectedId={selected?.id ?? null} onSelect={handleSelect} />
          ))}
        </div>
        <div style={{ overflowY: 'auto' }}>
          {!selected && (
            <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>왼쪽에서 노드를 선택하세요.</p>
          )}
          {selected && (
            <div style={{
              border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)',
              padding: 'var(--space-3)', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 12, color: 'var(--color-text-muted)' }}>
                <span className="krds-badge xsmall bg-information">{NODE_TYPE_LABELS[selected.node_type] ?? selected.node_type}</span>
                {selected.page_number != null && <span>{selected.page_number}페이지</span>}
                {selected.user_corrected && <span style={{ color: '#2563eb' }}>사용자 보정됨</span>}
              </div>
              {selected.text && (
                <p style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap', margin: 0 }}>{selected.text}</p>
              )}
              <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
                <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                  제목 레벨
                  <input
                    type="number"
                    value={levelInput}
                    onChange={(e) => setLevelInput(e.target.value)}
                    placeholder="예: 1 (H1)"
                    style={{ marginLeft: 6, width: 60, fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4, padding: '2px 6px' }}
                  />
                </label>
                <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                  노드 유형
                  <select
                    className="krds-form-select"
                    value={typeInput}
                    onChange={(e) => setTypeInput(e.target.value)}
                    style={{ marginLeft: 6, fontSize: 12 }}
                  >
                    {NODE_TYPES.map((t) => (
                      <option key={t} value={t}>{NODE_TYPE_LABELS[t] ?? t}</option>
                    ))}
                  </select>
                </label>
              </div>
              {selected.span_start != null && (
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  원문 위치 span {selected.span_start}–{selected.span_end}
                </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={updateNode.isPending}
                  className="krds-btn primary small"
                  style={{ cursor: 'pointer' }}
                >
                  보정 저장
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      <div style={{ fontSize: 12, color: 'var(--color-text-muted)', borderTop: '1px solid #e2e8f0', paddingTop: 'var(--space-2)' }}>
        노드 {nodes.length}개 · 제목 {(counts.HEADING ?? 0) + (counts.SECTION ?? 0)} · 문단 {counts.PARAGRAPH ?? 0} · 표 {counts.TABLE ?? 0} · 사용자 보정 {correctedCount}
      </div>
    </div>
  )
}
