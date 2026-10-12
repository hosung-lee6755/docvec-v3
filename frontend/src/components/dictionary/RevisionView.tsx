import { Clock, Loader2 } from 'lucide-react'
import { useDictionaryRevisions } from '../../hooks/useDictionary'

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

  return (
    <div className="dict-card" style={{ padding: 'var(--space-4)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>버전 이력</h2>
        <span style={{
          fontSize: 11, fontWeight: 600, color: 'var(--color-accent)', background: 'rgba(99,102,241,0.15)',
          borderRadius: 999, padding: '2px 8px',
        }}>
          최근 {revisionsData?.revisions.length ?? 0}건
        </span>
      </div>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 'var(--space-4)' }}>
        사전 항목의 추가·수정·삭제·엑셀 가져오기 이력입니다. 변경 전/후 값은 표시하지 않으며, 누가·언제·무엇을 했는지만 보여줍니다.
      </p>

      {revisionsLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
          <Loader2 size={24} style={{ animation: 'dict-spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
        </div>
      )}

      {!revisionsLoading && (revisionsData?.revisions.length ?? 0) === 0 && (
        <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
          <Clock size={40} style={{ margin: '0 auto var(--space-3)', display: 'block', opacity: 0.4 }} />
          <p style={{ fontSize: 13 }}>변경 이력이 없습니다.</p>
        </div>
      )}

      {!revisionsLoading && (revisionsData?.revisions.length ?? 0) > 0 && (
        <div className="krds-table-wrap" style={{ overflowX: 'auto' }}>
          <table className="tbl col data">
            <caption className="sr-only">사전 버전 이력</caption>
            <thead>
              <tr>
                <th scope="col" style={{ width: '8%' }}>버전</th>
                <th scope="col">용어</th>
                <th scope="col" style={{ width: '10%' }}>유형</th>
                <th scope="col" style={{ width: '10%' }}>변경</th>
                <th scope="col" style={{ width: '14%' }}>작성자</th>
                <th scope="col" style={{ width: '18%' }}>일시</th>
              </tr>
            </thead>
            <tbody>
              {revisionsData?.revisions.map((rev) => (
                <tr key={rev.version} className="dict-row">
                  <td>{rev.version}</td>
                  <td>{rev.entry_term ?? <span style={{ color: 'var(--color-text-muted)' }}>(삭제된 항목)</span>}</td>
                  <td>{rev.entry_type ? TABS.find((t) => t.type === rev.entry_type)?.label ?? rev.entry_type : '-'}</td>
                  <td>{REVISION_CHANGE_LABELS[rev.change_type] ?? rev.change_type}</td>
                  <td>{rev.created_by_name ?? <span style={{ color: 'var(--color-text-muted)' }}>-</span>}</td>
                  <td>{new Date(rev.created_at).toLocaleString('ko-KR')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
