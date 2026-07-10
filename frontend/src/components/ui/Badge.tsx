const STATUS_COLOR: Record<string, string> = {
  QUEUED: 'var(--color-text-muted)',
  INDEXED: 'var(--color-success)',
  FAILED: 'var(--color-danger)',
  INGESTING: 'var(--color-accent)',
  PARSING: 'var(--color-accent)',
  STRUCTURING: 'var(--color-accent)',
  NORMALIZING: 'var(--color-accent)',
  CHUNKING: 'var(--color-accent)',
  EMBEDDING: 'var(--color-accent)',
  UPLOADING: 'var(--color-accent)',
  REVIEW_PENDING: 'var(--color-warning)',
  REFINING: 'var(--color-warning)',
  CANCELLED: 'var(--color-text-muted)',
}

const STATUS_LABEL: Record<string, string> = {
  QUEUED: '대기',
  INDEXED: '완료',
  FAILED: '실패',
  INGESTING: '처리중',
  PARSING: '파싱중',
  STRUCTURING: '구조화',
  NORMALIZING: '정규화',
  CHUNKING: '청킹',
  EMBEDDING: '임베딩',
  UPLOADING: '업로드',
  REVIEW_PENDING: '검토대기',
  REFINING: '정제중',
  CANCELLED: '취소',
}

interface BadgeProps {
  status: string
  label?: string
}

export function Badge({ status, label }: BadgeProps) {
  const color = STATUS_COLOR[status] ?? 'var(--color-text-muted)'
  const text = label ?? STATUS_LABEL[status] ?? status

  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px var(--space-2)',
        borderRadius: 'var(--radius-sm)',
        fontSize: 11,
        fontWeight: 600,
        color: '#fff',
        background: color,
        lineHeight: 1.6,
      }}
    >
      {text}
    </span>
  )
}
