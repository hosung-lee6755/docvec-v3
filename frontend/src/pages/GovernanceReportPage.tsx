import { useState } from 'react'
import { FileDown, ShieldOff } from 'lucide-react'
import { useDownloadGovernanceReport } from '../hooks/useAnswerTraces'
import { useAuthStore } from '../store/authStore'
import { Alert, Button, Card, DescriptionList, EmptyState, ErrorAlert, Field, Input, Page, PageBody, PageHeader, Stat, StatStrip } from '../components/ui'

const DAY_MS = 24 * 60 * 60 * 1000
const DEFAULT_DAYS = 30
const MAX_RANGE_DAYS = 366

function toDateInput(date: Date): string {
  return date.toISOString().slice(0, 10)
}

function rangeDays(from: string, to: string): number {
  const diff = Date.parse(to) - Date.parse(from)
  return Number.isNaN(diff) ? 0 : Math.floor(diff / DAY_MS) + 1
}

const SECTIONS = [
  { key: '위험관리', detail: '보안등급별 문서 수, 접근 제한 문서 수, 기간 중 권한 변경 이력' },
  { key: '설명', detail: '답변 수, 근거 검증 결과, 재검색 비율, 인용 없는 답변, 모델별 답변 수' },
  { key: '이용자 보호', detail: '개인정보 탐지·처리 건수, 생성물 표시 현황' },
  { key: '사람의 감독', detail: '관리 조치 이력, 근거 검증에 실패한 답변 목록' },
  { key: '기록 보관', detail: '추적 기록 건수와 보관 범위, 조회 감사 건수' },
]

export default function GovernanceReportPage() {
  const currentUser = useAuthStore((s) => s.user)
  const today = new Date()
  const [fromDate, setFromDate] = useState(toDateInput(new Date(today.getTime() - DEFAULT_DAYS * DAY_MS)))
  const [toDate, setToDate] = useState(toDateInput(today))
  const download = useDownloadGovernanceReport()

  if (currentUser?.role !== 'admin') {
    return (
      <Page>
        <EmptyState icon={<ShieldOff size={48} aria-hidden="true" />} title="관리자만 접근할 수 있습니다." />
      </Page>
    )
  }

  const isRangeValid = fromDate !== '' && toDate !== '' && fromDate <= toDate
  const days = isRangeValid ? rangeDays(fromDate, toDate) : 0
  const isTooLong = days > MAX_RANGE_DAYS
  const handleDownload = () =>
    download.mutate({ from_date: `${fromDate}T00:00:00Z`, to_date: `${toDate}T23:59:59Z` })

  return (
    <Page>
      <PageHeader title="AI 기본법 근거 자료" subtitle="운영 기록을 제34조 관련 항목별로 정리한 Word 문서입니다." />
      <StatStrip>
        <Stat label="선택 기간" value={isRangeValid ? `${days}일` : '-'} tone={isTooLong ? 'danger' : 'default'} hint={`최대 ${MAX_RANGE_DAYS}일`} />
        <Stat label="문서에 담기는 항목" value={SECTIONS.length} />
        <Stat label="날짜 기준" value="UTC" />
      </StatStrip>

      <PageBody>
        <div style={{ maxWidth: 760, display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          <p style={{ margin: 0, color: 'var(--color-text-muted)', lineHeight: 'var(--leading-normal)', fontSize: 'var(--text-sm)' }}>
            기간을 정하면 근거 자료를 내려받습니다. 시스템은 수치와 설정만 채우고, 해석이 필요한 칸은 &quot;법률 검토 필요&quot;로 비워 둡니다.
            이 문서가 법적 의무를 충족했음을 증명하지는 않습니다.
          </p>

          <Card title="기간 정하기">
            <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <Field label="시작일">
                {(id) => <Input id={id} type="date" controlSize="sm" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />}
              </Field>
              <Field label="종료일">
                {(id) => <Input id={id} type="date" controlSize="sm" value={toDate} onChange={(e) => setToDate(e.target.value)} />}
              </Field>
              <Button
                variant="primary"
                size="sm"
                disabled={!isRangeValid || download.isPending}
                onClick={handleDownload}
                icon={<FileDown size={14} aria-hidden="true" />}
              >
                {download.isPending ? '만드는 중…' : '근거 자료 내려받기'}
              </Button>
            </div>
            {!isRangeValid && <div style={{ marginTop: 'var(--space-3)' }}><Alert tone="danger">시작일은 종료일보다 늦을 수 없습니다.</Alert></div>}
            {download.isError && <div style={{ marginTop: 'var(--space-3)' }}><ErrorAlert error={download.error} message="근거 자료를 만들지 못했습니다." /></div>}
          </Card>

          <Card title="문서에 담기는 항목">
            <DescriptionList items={SECTIONS.map((s) => ({ key: s.key, term: s.key, detail: s.detail }))} />
          </Card>

          <p className="ds-cell-muted" style={{ margin: 0, fontSize: 'var(--text-xs)' }}>
            내려받은 기록은 감사 로그에 남습니다. 날짜는 UTC 기준입니다.
          </p>
        </div>
      </PageBody>
    </Page>
  )
}
