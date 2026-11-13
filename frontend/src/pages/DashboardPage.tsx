import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  FolderPlus, Upload, FileText, History, FolderOpen, Search, MessageSquare,
  FolderKanban, ArrowRight, Loader2,
} from 'lucide-react'
import { apiClient } from '../lib/apiClient'
import { useDocuments } from '../hooks/useDocuments'
import { useSearchHistory } from '../hooks/useSearchHistory'
import { useProjects } from '../hooks/useProjects'
import { useAuthStore } from '../store/authStore'
import { PROCESSING_STATUSES } from '../lib/documentStatus'
import { Button, Card, ErrorAlert, Page, PageBody, PageHeader, Stat, StatStrip, StatusBadge } from '../components/ui'
import type { StatTone } from '../components/ui'
import '../styles/screens/user.css'

interface Stats {
  total_documents: number
  processing: number
  indexed: number
  collections: number
}

async function fetchStats(): Promise<Stats> {
  const { data } = await apiClient.get<Stats>('/stats')
  return data
}

const GREETINGS = [
  { before: 5, text: '늦은 밤이네요' },
  { before: 11, text: '좋은 아침입니다' },
  { before: 14, text: '점심 잘 챙기셨나요' },
  { before: 18, text: '오늘 하루도 힘내세요' },
  { before: 22, text: '오늘 하루 고생하셨어요' },
  { before: 24, text: '늦은 밤이네요' },
]

function greetingForHour(hour: number): string {
  return GREETINGS.find((g) => hour < g.before)?.text ?? '반갑습니다'
}

const QUICK_LINKS = [
  { to: '/projects', icon: FolderKanban, label: '프로젝트', desc: '팀 작업 공간' },
  { to: '/collections', icon: FolderOpen, label: '컬렉션', desc: '문서 묶음 관리' },
  { to: '/search', icon: Search, label: '검색', desc: '의미·하이브리드 검색' },
  { to: '/chat', icon: MessageSquare, label: '채팅', desc: 'AI에게 질문하기' },
]

interface SummaryStat {
  label: string
  value: number | undefined
  tone?: StatTone
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [isPageVisible, setIsPageVisible] = useState(!document.hidden)
  const [errorCount, setErrorCount] = useState(0)

  useEffect(() => {
    const handleVisibilityChange = () => {
      setIsPageVisible(!document.hidden)
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [])

  // Calculate refetch interval: pause when tab hidden, back off on errors
  const baseInterval = 10000
  const refetchInterval = isPageVisible
    ? errorCount > 2 ? false : errorCount > 0 ? 30000 : baseInterval
    : false // Pause when tab is hidden

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['stats'],
    queryFn: fetchStats,
    refetchInterval,
  })

  // Track error count for backoff
  useEffect(() => {
    if (isError) {
      setErrorCount((prev) => Math.min(prev + 1, 3))
    } else if (!isLoading) {
      setErrorCount(0)
    }
  }, [isError, isLoading])
  // limit=10으로 최근 문서 10건만 가져와 클라이언트에서 필터링하면, 처리중인
  // 문서가 10건보다 많거나 최근 10건 밖에 있을 때 위젯에서 누락됐다(2026-07-30,
  // "처리중인 작업 10건이라고 표기됨"). 서버에서 11개 processing 상태를 직접
  // 필터링해 전수 조회한다.
  const { data: processingData } = useDocuments({
    status: PROCESSING_STATUSES.join(','), limit: 200, sortBy: 'created_at', order: 'desc',
  })
  const { data: recentDocs } = useDocuments({ page: 1, limit: 10, sortBy: 'created_at', order: 'desc' })
  const { data: recentSearches } = useSearchHistory(5)
  const { data: projectsData } = useProjects()

  const processingDocs = processingData?.items ?? []
  const greeting = greetingForHour(new Date().getHours())
  const today = new Date().toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'long' })

  // 요약 띠는 이 화면이 이미 받아 온 /stats 값만 쓴다(새 API 호출 없음).
  const summaryStats: SummaryStat[] = [
    { label: '총 문서', value: data?.total_documents },
    { label: '처리 중', value: data?.processing, tone: (data?.processing ?? 0) > 0 ? 'warning' : 'default' },
    { label: '색인 완료', value: data?.indexed },
    { label: '컬렉션', value: data?.collections },
  ]

  return (
    <Page>
      <PageHeader
        title={<>{greeting}, <span className="user-dash__name">{user?.username ?? '사용자'}</span>님</>}
        subtitle={today}
        actions={(
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigate('/collections', { state: { openCreate: true } })}
              icon={<FolderPlus size={14} />}
            >
              새 컬렉션
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => navigate('/documents', { state: { openUpload: true } })}
              icon={<Upload size={14} />}
            >
              문서 업로드
            </Button>
          </>
        )}
      />

      <StatStrip label="문서 요약">
        {summaryStats.map(({ label, value, tone }) => (
          <Stat key={label} label={label} value={isLoading ? '···' : (value ?? 0)} tone={tone} />
        ))}
      </StatStrip>

      <PageBody>
        {isError && <ErrorAlert error={error} message="요약 통계를 불러오지 못했습니다. 위 숫자는 마지막으로 받은 값이거나 비어 있습니다." onRetry={() => refetch()} />}
        {processingDocs.length > 0 && (
          <Card
            title={(
              <span className="user-dash__warn-title">
                <Loader2 size={14} className="user-spin-icon" aria-hidden="true" />
                처리 중인 작업 {processingDocs.length}건
              </span>
            )}
            isFlush
          >
            <div className="user-dash__list user-dash__list--scroll">
              {processingDocs.map((doc) => (
                <button
                  key={doc.id}
                  type="button"
                  className="user-dash__row"
                  onClick={() => navigate(`/documents/${doc.id}`)}
                >
                  <span className="user-dash__row-main">
                    <span className="user-dash__pulse" aria-hidden="true" />
                    <span className="user-dash__row-text">{doc.original_filename}</span>
                  </span>
                  <StatusBadge status={doc.status} />
                </button>
              ))}
            </div>
          </Card>
        )}

        {!!projectsData?.items.length && (
          <section className="user-dash__projects" aria-label="내 프로젝트">
            <div className="user-dash__section-head">
              <span className="user-dash__section-title">
                <FolderKanban size={14} /> 내 프로젝트
              </span>
              <Button variant="ghost" size="sm" onClick={() => navigate('/projects')}>
                전체 보기 <ArrowRight size={12} />
              </Button>
            </div>
            <div className="user-dash__project-row">
              {projectsData.items.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="user-dash__project"
                  onClick={() => navigate(`/projects/${p.id}`)}
                >
                  <span className="user-dash__project-name">{p.name}</span>
                  <span className="user-dash__project-meta">
                    <span>컬렉션 {p.collection_count}</span>
                    <span>멤버 {p.member_count}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>
        )}

        <div className="user-dash__grid">
          <Card title="빠른 실행">
            <div className="user-dash__list">
              {QUICK_LINKS.map(({ to, icon: Icon, label, desc }) => (
                <button key={to} type="button" className="user-dash__quick" onClick={() => navigate(to)}>
                  <span className="user-dash__quick-icon"><Icon size={15} /></span>
                  <span className="user-dash__quick-text">
                    <span className="user-dash__quick-label">{label}</span>
                    <span className="user-dash__quick-desc">{desc}</span>
                  </span>
                  <ArrowRight size={13} className="user-dash__quick-arrow" aria-hidden="true" />
                </button>
              ))}
            </div>
          </Card>

          <Card title={<span className="user-dash__section-title"><FileText size={14} /> 최근 문서</span>}>
            {(recentDocs?.items.length ?? 0) === 0 && (
              <p className="user-dash__muted">업로드된 문서가 없습니다.</p>
            )}
            <div className="user-dash__list">
              {recentDocs?.items.slice(0, 6).map((doc) => (
                <button
                  key={doc.id}
                  type="button"
                  className="user-dash__row"
                  onClick={() => navigate(`/documents/${doc.id}`)}
                >
                  <span className="user-dash__row-text">{doc.original_filename}</span>
                  <StatusBadge status={doc.status} />
                </button>
              ))}
            </div>
          </Card>

          <Card title={<span className="user-dash__section-title"><History size={14} /> 최근 검색</span>}>
            {(recentSearches?.items.length ?? 0) === 0 && (
              <p className="user-dash__muted">검색 기록이 없습니다.</p>
            )}
            <div className="user-dash__list">
              {recentSearches?.items.map((h) => (
                <button key={h.id} type="button" className="user-dash__row" onClick={() => navigate('/search')}>
                  <span className="user-dash__row-text">{h.query}</span>
                  <span className="user-dash__row-meta">{h.result_count}건</span>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </PageBody>
    </Page>
  )
}
