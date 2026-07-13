import { useBlockTypes } from '../../hooks/useWorkflows'

const BLOCK_LABELS: Record<string, string> = {
  input: '입력',
  preprocess: '전처리',
  classify: '분류',
  extract_entities: '개체 추출',
  extract_keywords: '키워드 추출',
  summarize: '요약',
  validate: '검증',
  branch: '조건 분기',
  merge: '병합',
  postprocess: '후처리',
  output: '출력',
}

interface BlockPaletteProps {
  onAddBlock: (blockType: string) => void
}

export default function BlockPalette({ onAddBlock }: BlockPaletteProps) {
  const { data, isLoading } = useBlockTypes()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', padding: 'var(--space-3)' }}>
      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-muted)' }}>블록 목록</span>
      {isLoading && <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>불러오는 중...</span>}
      {data?.items.map((blockType) => (
        <button
          key={blockType}
          type="button"
          onClick={() => onAddBlock(blockType)}
          style={{
            textAlign: 'left',
            padding: 'var(--space-2) var(--space-3)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--color-border)',
            background: 'var(--color-surface)',
            fontSize: 13,
            cursor: 'pointer',
          }}
        >
          {BLOCK_LABELS[blockType] ?? blockType}
        </button>
      ))}
    </div>
  )
}
