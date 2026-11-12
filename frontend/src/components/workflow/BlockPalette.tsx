import { useMemo, useState } from 'react'
import { useBlockTypes } from '../../hooks/useWorkflows'
import { BLOCK_CATEGORIES, PREPROCESS_BLOCK_CATEGORIES, getBlockMeta } from '../../lib/workflowBlocks'
import { SearchInput } from '../ui'
import '../../styles/screens/pipeline.css'

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
    <div className="pipeline-palette">
      <SearchInput
        label="블록 검색"
        placeholder="블록 검색"
        width="100%"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      {isLoading && <span className="wf-muted">불러오는 중...</span>}

      {groups.map((group) => (
        <div key={group.category} className="pipeline-palette__group">
          <span className="pipeline-palette__category">{group.category}</span>
          {group.blockTypes.map((blockType) => {
            const meta = getBlockMeta(blockType)
            const Icon = meta.icon
            return (
              <button
                key={blockType}
                type="button"
                className="pipeline-palette__item"
                onClick={() => onAddBlock(blockType)}
                title={meta.description}
              >
                {/* 블록 범주색은 구분용이라 인라인 색을 그대로 쓴다. */}
                <span className="pipeline-palette__icon" style={{ background: `${meta.color}26`, color: meta.color }}>
                  <Icon size={14} aria-hidden="true" />
                </span>
                {meta.label}
              </button>
            )
          })}
        </div>
      ))}

      {!isLoading && groups.length === 0 && (
        <span className="wf-muted" style={{ padding: '0 var(--space-2)' }}>검색 결과가 없습니다.</span>
      )}
    </div>
  )
}
