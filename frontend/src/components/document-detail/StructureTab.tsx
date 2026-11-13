import { useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import {
  useDocumentNodes, useUpdateDocumentNode, type DocumentNodeItem,
} from '../../hooks/useDocumentStructure'
import { useDocumentRuns, useReprocessImpact } from '../../hooks/useDocumentRuns'
import { useWorkflowRun } from '../../hooks/useWorkflows'
import { ErrorText } from '../ui'

const STRUCTURE_ANALYZE_BLOCK_TYPE = 'structure_analyze'
const EMPTY_NODES: DocumentNodeItem[] = []

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
          background: node.id === selectedId ? 'var(--color-primary-subtle)' : 'transparent', cursor: 'pointer',
          color: node.id === selectedId ? 'var(--color-accent)' : 'inherit',
        }}
      >
        <span style={{ color: 'var(--color-text-subtle)', flexShrink: 0 }}>{NODE_TYPE_ICONS[node.node_type] ?? '·'}</span>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {node.text?.slice(0, 60) || NODE_TYPE_LABELS[node.node_type] || node.node_type}
        </span>
        {node.user_corrected && <span style={{ flexShrink: 0, color: 'var(--color-primary)', fontSize: 11 }}>●</span>}
      </button>
      {node.children.map((child) => (
        <TreeRow key={child.id} node={child} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} />
      ))}
    </div>
  )
}

interface StructureTabProps {
  documentId: string
  onViewInOriginal?: (pageNumber: number) => void
  onReprocessFromStructure?: (blockInstanceId: string) => void
}

export default function StructureTab({ documentId, onViewInOriginal, onReprocessFromStructure }: StructureTabProps) {
  const { data, isLoading, isError, error } = useDocumentNodes(documentId)
  const updateNode = useUpdateDocumentNode()
  const [selected, setSelected] = useState<DocumentNodeItem | null>(null)
  const [levelInput, setLevelInput] = useState('')
  const [typeInput, setTypeInput] = useState('')
  // 메타 정보 생성.txt 2절 — HWP/HWPX/Docling 경로처럼 style_name/font_size/
  // font_name이 자동 생성 안 되는 노드의 수동 입력(9항목 펀치리스트 후속,
  // 2026-07-24).
  const [styleNameInput, setStyleNameInput] = useState('')
  const [fontSizeInput, setFontSizeInput] = useState('')
  const [fontNameInput, setFontNameInput] = useState('')
  const [showReprocessBanner, setShowReprocessBanner] = useState(false)

  // `?? []`를 렌더마다 새로 만들면 useMemo 의존성이 매번 바뀌므로 안정된 참조를 쓴다.
  const nodes = data?.nodes ?? EMPTY_NODES
  const tree = useMemo(() => buildTree(nodes), [nodes])

  // 보정 저장 후 "구조 변경이 청크 N개에 영향" 배너(와이어프레임 §3.2)에
  // 쓸 구조분석 블록의 영향 범위 — history 탭의 "[이 블록부터 재처리]"와
  // 동일하게 structure_analyze 블록 instance를 재처리 시작점으로 쓴다.
  const { data: runsData } = useDocumentRuns(documentId)
  const latestRunId = runsData?.runs[0]?.id ?? null
  const { data: runDetail } = useWorkflowRun(latestRunId)
  const structureStep = runDetail?.steps.find((s) => s.block_type === STRUCTURE_ANALYZE_BLOCK_TYPE) ?? null
  const { data: impact } = useReprocessImpact(
    documentId, null, showReprocessBanner ? structureStep?.block_instance_id ?? null : null,
  )

  const handleSelect = (node: DocumentNodeItem) => {
    setSelected(node)
    setLevelInput(node.level != null ? String(node.level) : '')
    setTypeInput(node.node_type)
    const style = (node.style ?? {}) as { style_name?: string; font_size?: number; font_name?: string }
    setStyleNameInput(style.style_name ?? '')
    setFontSizeInput(style.font_size != null ? String(style.font_size) : '')
    setFontNameInput(style.font_name ?? '')
    setShowReprocessBanner(false)
  }

  const handleSave = () => {
    if (!selected) return
    updateNode.mutate({
      documentId,
      nodeId: selected.id,
      level: levelInput.trim() ? Number(levelInput) : undefined,
      nodeType: typeInput !== selected.node_type ? typeInput : undefined,
      styleName: styleNameInput || undefined,
      fontSize: fontSizeInput ? Number(fontSizeInput) : undefined,
      fontName: fontNameInput || undefined,
    }, { onSuccess: () => setShowReprocessBanner(true) })
  }

  if (isError) return <ErrorText error={error} message="문서 구조를 불러오지 못했습니다." />

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
        <div style={{ overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)' }}>
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
              border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)',
              padding: 'var(--space-3)', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 12, color: 'var(--color-text-muted)' }}>
                <span className="ds-badge ds-badge--info">{NODE_TYPE_LABELS[selected.node_type] ?? selected.node_type}</span>
                {selected.page_number != null && <span>{selected.page_number}페이지</span>}
                {selected.user_corrected && <span style={{ color: 'var(--color-primary)' }}>사용자 보정됨</span>}
              </div>
              {selected.text && (
                <p style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap', margin: 0 }}>{selected.text}</p>
              )}
              {selected.style && Object.keys(selected.style).length > 0 && (
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  스타일 {Object.entries(selected.style).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                </div>
              )}
              <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
                <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                  제목 레벨
                  <input
                    type="number"
                    value={levelInput}
                    onChange={(e) => setLevelInput(e.target.value)}
                    placeholder="예: 1 (H1)"
                    style={{ marginLeft: 6, width: 60, fontSize: 12, border: '1px solid var(--color-border)', borderRadius: 4, padding: '2px 6px' }}
                  />
                </label>
                <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                  노드 유형
                  <select
                    className="ds-select"
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
              {/* 메타 정보 생성.txt 2절 — 자동 생성 불가 노드(HWP/HWPX,
                  Docling)의 style_name/font_size/font_name 수동 입력. */}
              <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
                <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                  스타일명
                  <input
                    value={styleNameInput}
                    onChange={(e) => setStyleNameInput(e.target.value)}
                    placeholder="예: Heading1"
                    style={{ marginLeft: 6, width: 90, fontSize: 12, border: '1px solid var(--color-border)', borderRadius: 4, padding: '2px 6px' }}
                  />
                </label>
                <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                  글자 크기
                  <input
                    type="number"
                    value={fontSizeInput}
                    onChange={(e) => setFontSizeInput(e.target.value)}
                    placeholder="pt"
                    style={{ marginLeft: 6, width: 60, fontSize: 12, border: '1px solid var(--color-border)', borderRadius: 4, padding: '2px 6px' }}
                  />
                </label>
                <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                  글꼴
                  <input
                    value={fontNameInput}
                    onChange={(e) => setFontNameInput(e.target.value)}
                    placeholder="예: 맑은 고딕"
                    style={{ marginLeft: 6, width: 100, fontSize: 12, border: '1px solid var(--color-border)', borderRadius: 4, padding: '2px 6px' }}
                  />
                </label>
              </div>
              {selected.span_start != null && (
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span>원문 위치 span {selected.span_start}–{selected.span_end}</span>
                  {onViewInOriginal && selected.page_number != null && (
                    <button
                      type="button"
                      onClick={() => onViewInOriginal(selected.page_number as number)}
                      className="ds-btn ds-btn--ghost ds-btn--sm"
                      style={{ cursor: 'pointer', fontSize: 11, padding: 0 }}
                    >
                      원문 대조에서 보기
                    </button>
                  )}
                </div>
              )}
              {showReprocessBanner && impact && (
                <div style={{
                  fontSize: 12, color: 'var(--color-warning)', background: 'var(--color-warning-bg)',
                  border: '1px solid var(--color-warning-border)', borderRadius: 'var(--radius-sm)',
                  padding: 'var(--space-2)', display: 'flex', alignItems: 'center', gap: 8,
                }}>
                  <span>구조 변경이 청크 {impact.affectedChunkCount}개에 영향 —</span>
                  {structureStep && onReprocessFromStructure && (
                    <button
                      type="button"
                      onClick={() => onReprocessFromStructure(structureStep.block_instance_id)}
                      className="ds-btn ds-btn--ghost ds-btn--sm"
                      style={{ cursor: 'pointer', fontSize: 12, padding: 0, color: 'var(--color-warning)', textDecoration: 'underline' }}
                    >
                      지금 재처리
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setShowReprocessBanner(false)}
                    className="ds-btn ds-btn--ghost ds-btn--sm"
                    style={{ cursor: 'pointer', fontSize: 12, padding: 0, color: 'var(--color-warning)' }}
                  >
                    나중에
                  </button>
                </div>
              )}
              {updateNode.isError && <ErrorText error={updateNode.error} message="구조 보정을 저장하지 못했습니다." />}
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={updateNode.isPending}
                  className="ds-btn ds-btn--primary ds-btn--sm"
                  style={{ cursor: 'pointer' }}
                >
                  보정 저장
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      <div style={{ fontSize: 12, color: 'var(--color-text-muted)', borderTop: '1px solid var(--color-border)', paddingTop: 'var(--space-2)' }}>
        노드 {nodes.length}개 · 제목 {(counts.HEADING ?? 0) + (counts.SECTION ?? 0)} · 문단 {counts.PARAGRAPH ?? 0} · 표 {counts.TABLE ?? 0} · 사용자 보정 {correctedCount}
      </div>
    </div>
  )
}
