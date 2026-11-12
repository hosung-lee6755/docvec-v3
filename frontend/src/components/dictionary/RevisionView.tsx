import { Clock, Loader2 } from 'lucide-react'
import { useDictionaryRevisions } from '../../hooks/useDictionary'
import { Badge, Card, EmptyState } from '../ui'
import '../../styles/screens/pipeline.css'

const TABS: { type: string; label: string }[] = [
  { type: 'stopword', label: '불용어' },
  { type: 'synonym', label: '동의어' },
  { type: 'custom_word', label: '사용자 사전' },
]

const REVISION_CHANGE_LABELS: Record<string, string> = {
  CREATE: '추가', UPDATE: '수정', DELETE: '삭제', IMPORT: '엑셀 가져오기',
}

export function RevisionView() {
  const { data: revisionsData, isLoading: revisionsLoading } = useDictionaryRevisions(true)
  const count = revisionsData?.revisions.length ?? 0

  return (
    <Card
      title={(
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          버전 이력
          <Badge tone="info">최근 {count}건</Badge>
        </span>
      )}
    >
      <p className="wf-muted" style={{ marginBottom: 'var(--space-3)' }}>
        사전 항목의 추가·수정·삭제·엑셀 가져오기 이력입니다. 변경 전/후 값은 표시하지 않으며, 누가·언제·무엇을 했는지만 보여줍니다.
      </p>

      {revisionsLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
          <Loader2 size={24} className="pipeline-spin" style={{ color: 'var(--color-text-muted)' }} aria-label="불러오는 중" />
        </div>
      )}

      {!revisionsLoading && count === 0 && (
        <EmptyState
          icon={<Clock size={40} aria-hidden="true" />}
          title="변경 이력이 없습니다."
        />
      )}

      {!revisionsLoading && count > 0 && (
        <div className="ds-table-wrap">
          <table className="ds-table">
            <caption className="sr-only">사전 버전 이력</caption>
            <thead>
              <tr>
                <th scope="col" className="ds-cell-num">버전</th>
                <th scope="col">용어</th>
                <th scope="col">유형</th>
                <th scope="col">변경</th>
                <th scope="col">작성자</th>
                <th scope="col">일시</th>
              </tr>
            </thead>
            <tbody>
              {revisionsData?.revisions.map((rev) => (
                <tr key={rev.version}>
                  <td className="ds-cell-num pipeline-cell-mono">{rev.version}</td>
                  <td>{rev.entry_term ?? <span className="ds-cell-muted">(삭제된 항목)</span>}</td>
                  <td>{rev.entry_type ? TABS.find((t) => t.type === rev.entry_type)?.label ?? rev.entry_type : '-'}</td>
                  <td>{REVISION_CHANGE_LABELS[rev.change_type] ?? rev.change_type}</td>
                  <td>{rev.created_by_name ?? <span className="ds-cell-muted">-</span>}</td>
                  <td className="ds-cell-muted">{new Date(rev.created_at).toLocaleString('ko-KR')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
