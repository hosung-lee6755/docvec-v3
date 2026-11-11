import { useState } from 'react'
import { FileDown, ShieldOff } from 'lucide-react'
import { useDownloadGovernanceReport } from '../hooks/useAnswerTraces'
import { useAuthStore } from '../store/authStore'

const DAY_MS = 24 * 60 * 60 * 1000
const DEFAULT_DAYS = 30

function toDateInput(date: Date): string {
  return date.toISOString().slice(0, 10)
}

const SECTIONS = [
  ['위험관리', '보안등급별 문서 수, 접근 제한 문서 수, 기간 중 권한 변경 이력'],
  ['설명', '답변 수, 근거 검증 결과, 재검색 비율, 인용 없는 답변, 모델별 답변 수'],
  ['이용자 보호', '개인정보 탐지·처리 건수, 생성물 표시 현황'],
  ['사람의 감독', '관리 조치 이력, 근거 검증에 실패한 답변 목록'],
  ['기록 보관', '추적 기록 건수와 보관 범위, 조회 감사 건수'],
] as const

export default function GovernanceReportPage() {
  const currentUser = useAuthStore((s) => s.user)
  const today = new Date()
  const [fromDate, setFromDate] = useState(toDateInput(new Date(today.getTime() - DEFAULT_DAYS * DAY_MS)))
  const [toDate, setToDate] = useState(toDateInput(today))
  const download = useDownloadGovernanceReport()

  if (currentUser?.role !== 'admin') {
    return (
      <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
        <ShieldOff size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
        <p>관리자만 접근할 수 있습니다.</p>
      </div>
    )
  }

  const isRangeValid = fromDate !== '' && toDate !== '' && fromDate <= toDate
  const handleDownload = () =>
    download.mutate({ from_date: `${fromDate}T00:00:00Z`, to_date: `${toDate}T23:59:59Z` })

  return (
    <div style={{ maxWidth: 760 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 'var(--space-2)' }}>AI 기본법 근거 자료</h1>
      <p style={{ color: 'var(--color-text-muted)', marginBottom: 'var(--space-4)', lineHeight: 1.6 }}>
        기간을 정하면 운영 기록을 제34조 관련 항목별로 정리한 Word 문서를 내려받습니다.
        시스템은 수치와 설정만 채우고, 해석이 필요한 칸은 &quot;법률 검토 필요&quot;로 비워 둡니다.
        이 문서가 법적 의무를 충족했음을 증명하지는 않습니다.
      </p>

      <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap', marginBottom: 'var(--space-4)' }}>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          시작일
          <input type="date" className="krds-input small" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
        </label>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          종료일
          <input type="date" className="krds-input small" value={toDate} onChange={(e) => setToDate(e.target.value)} />
        </label>
        <button
          type="button"
          className="krds-btn small primary"
          disabled={!isRangeValid || download.isPending}
          onClick={handleDownload}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          <FileDown size={14} />
          {download.isPending ? '만드는 중…' : '근거 자료 내려받기'}
        </button>
      </div>
      {!isRangeValid && <p role="alert" style={{ color: '#dc2626', fontSize: 13 }}>시작일은 종료일보다 늦을 수 없습니다.</p>}
      {download.isError && <p role="alert" style={{ color: '#dc2626', fontSize: 13 }}>근거 자료를 만들지 못했습니다. 기간은 최대 366일입니다.</p>}

      <h2 style={{ fontSize: 16, fontWeight: 700, margin: 'var(--space-6) 0 var(--space-2)' }}>문서에 담기는 항목</h2>
      <dl style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '8px var(--space-3)', fontSize: 14 }}>
        {SECTIONS.map(([title, body]) => (
          <div key={title} style={{ display: 'contents' }}>
            <dt style={{ fontWeight: 600 }}>{title}</dt>
            <dd style={{ margin: 0, color: 'var(--color-text-muted)' }}>{body}</dd>
          </div>
        ))}
      </dl>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 'var(--space-4)' }}>
        내려받은 기록은 감사 로그에 남습니다. 날짜는 UTC 기준입니다.
      </p>
    </div>
  )
}
