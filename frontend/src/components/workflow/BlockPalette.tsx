import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { useBlockTypes } from '../../hooks/useWorkflows'
import { BLOCK_CATEGORIES, PREPROCESS_BLOCK_CATEGORIES, getBlockMeta } from '../../lib/workflowBlocks'

interface BlockPaletteProps {
  onAddBlock: (blockType: string) => void
  // 워크플로우의 kind — PREPROCESS면 입력·추출/정제·정규화/구조·보호/분할·저장/
  // 품질·제어 카테고리만, ANALYSIS(또는 아직 모를 때)는 기존 5개 카테고리만 보여준다.
  workflowKind?: 'PREPROCESS' | 'ANALYSIS'
}

export default function BlockPalette({ onAddBlock, workflowKind }: BlockPaletteProps) {
  const { data, isLoading } = useBlockTypes()
  const [query, setQuery] = useState('')
  const categories = workflowKind === 'PREPROCESS' ? PREPROCESS_BLOCK_CATEGORIES : BLOCK_CATEGORIES

  const groups = useMemo(() => {
    const items = data?.items ?? []
    const q = query.trim()
    const filtered = q
      ? items.filter((item) => getBlockMeta(item.block_type).label.includes(q))
      : items
    return categories
      .map((category) => ({
        category,
        blockTypes: filtered.filter((item) => getBlockMeta(item.block_type).category === category).map((item) => item.block_type),
      }))
      .filter((group) => group.blockTypes.length > 0)
  }, [data, query, categories])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)', padding: 'var(--space-3)' }}>
      <div style={{ position: 'relative' }}>
        <Search size={14} style={{
          position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)',
          color: 'var(--color-text-muted)', pointerEvents: 'none',
        }} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="블록 검색"
          className="krds-input small"
          style={{ width: '100%', paddingLeft: 30 }}
        />
      </div>

      {isLoading && <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>불러오는 중...</span>}

      {groups.map((group) => (
        <div key={group.category} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
          <span style={{
            fontSize: 11, fontWeight: 700, color: 'var(--color-text-muted)',
            textTransform: 'uppercase', letterSpacing: 0.4, padding: '0 var(--space-2)',
          }}>
            {group.category}
          </span>
          {group.blockTypes.map((blockType) => {
            const meta = getBlockMeta(blockType)
            const Icon = meta.icon
            return (
              <button
                key={blockType}
                type="button"
                onClick={() => onAddBlock(blockType)}
                title={meta.description}
                style={{
                  display: 'flex', alignItems: 'center', gap: 'var(--space-2)', textAlign: 'left',
                  padding: 'var(--space-2)', borderRadius: 'var(--radius-md)',
                  border: '1px solid transparent', background: 'transparent',
                  fontSize: 13, color: 'var(--color-text)', cursor: 'pointer',
                  transition: 'background var(--duration-fast), border-color var(--duration-fast)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--color-bg)'
                  e.currentTarget.style.borderColor = 'var(--color-border)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent'
                  e.currentTarget.style.borderColor = 'transparent'
                }}
              >
                <div style={{
                  width: 24, height: 24, borderRadius: 'var(--radius-sm)', flexShrink: 0,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: `${meta.color}26`, color: meta.color,
                }}>
                  <Icon size={14} />
                </div>
                {meta.label}
              </button>
            )
          })}
        </div>
      ))}

      {!isLoading && groups.length === 0 && (
        <span style={{ fontSize: 13, color: 'var(--color-text-muted)', padding: '0 var(--space-2)' }}>
          검색 결과가 없습니다.
        </span>
      )}
    </div>
  )
}
