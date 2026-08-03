import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  FolderPlus, Upload, FileText, History, FolderOpen, Search, MessageSquare,
  FolderKanban, ArrowRight, Loader2, Files, Layers, PackageCheck,
} from 'lucide-react'
import { apiClient } from '../lib/apiClient'
import { useDocuments } from '../hooks/useDocuments'
import { useSearchHistory } from '../hooks/useSearchHistory'
import { useProjects } from '../hooks/useProjects'
import { useAuthStore } from '../store/authStore'
import { PROCESSING_STATUSES, STATUS_BADGE_CLASSES, STATUS_LABELS } from '../lib/documentStatus'

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

export default function DashboardPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data, isLoading } = useQuery({ queryKey: ['stats'], queryFn: fetchStats, refetchInterval: 10000 })
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

  const stats = [
    { label: '총 문서', value: data?.total_documents, icon: Files, accent: '#818cf8', tint: 'rgba(99,102,241,0.16)' },
    {
      label: '처리 중', value: data?.processing, icon: Loader2, accent: '#fbbf24', tint: 'rgba(245,158,11,0.16)',
      spin: (data?.processing ?? 0) > 0,
    },
    { label: '색인 완료', value: data?.indexed, icon: PackageCheck, accent: '#34d399', tint: 'rgba(34,197,94,0.16)' },
    { label: '컬렉션', value: data?.collections, icon: Layers, accent: '#38bdf8', tint: 'rgba(56,189,248,0.16)' },
  ]

  return (
    <div>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
        @keyframes pulse-dot { 0%, 100% { opacity: 1; transform: scale(1) } 50% { opacity: .45; transform: scale(.7) } }
        .stat-tile { transition: transform var(--duration-fast) ease, border-color var(--duration-fast) ease; }
        .stat-tile:hover { transform: translateY(-2px); border-color: var(--tile-accent, #e2e8f0); }
        .row-link { transition: background var(--duration-fast) ease, padding-left var(--duration-fast) ease; border-radius: var(--radius-sm); }
        .row-link:hover { background: rgba(148,163,184,0.08); }
        .quick-tile { transition: transform var(--duration-fast) ease, background var(--duration-fast) ease, border-color var(--duration-fast) ease; }
        .quick-tile:hover { transform: translateY(-2px); background: rgba(99,102,241,0.10); border-color: rgba(99,102,241,0.35); }
        .quick-tile:hover .quick-arrow { opacity: 1; transform: translateX(0); }
        .quick-arrow { opacity: 0; transform: translateX(-4px); transition: opacity var(--duration-fast) ease, transform var(--duration-fast) ease; }
        .project-pill { transition: border-color var(--duration-fast) ease, background var(--duration-fast) ease; }
        .project-pill:hover { border-color: rgba(99,102,241,0.4); background: rgba(99,102,241,0.08); }
      `}</style>

      <div style={{
        display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
        marginBottom: 'var(--space-8)', flexWrap: 'wrap', gap: 'var(--space-4)',
      }}>
        <div>
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 6px', letterSpacing: 0.2 }}>
            {today}
          </p>
          <h1 style={{ fontSize: 24, fontWeight: 800, margin: 0, letterSpacing: -0.3 }}>
            {greeting}, <span style={{ color: '#4f46e5' }}>{user?.username ?? '사용자'}</span>님
          </h1>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
          <button
            type="button"
            className="krds-btn small tertiary"
            onClick={() => navigate('/collections', { state: { openCreate: true } })}
            style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}
          >
            <FolderPlus size={14} /> 새 컬렉션
          </button>
          <button
            type="button"
            className="krds-btn small primary"
            onClick={() => navigate('/documents', { state: { openUpload: true } })}
            style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}
          >
            <Upload size={14} /> 문서 업로드
          </button>
        </div>
      </div>

      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: 'var(--space-4)', marginBottom: 'var(--space-6)',
      }}>
        {stats.map(({ label, value, icon: Icon, accent, tint, spin }) => (
          <div
            key={label}
            className="stat-tile"
            style={{
              '--tile-accent': accent,
              padding: 'var(--space-5) var(--space-6)', background: '#ffffff',
              border: '1px solid #e2e8f0', borderRadius: 'var(--radius-lg)',
              position: 'relative', overflow: 'hidden',
            } as React.CSSProperties}
          >
            <div style={{
              position: 'absolute', top: 0, left: 0, right: 0, height: 3,
              background: `linear-gradient(90deg, ${accent}, transparent)`,
            }} />
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 'var(--space-3)' }}>
              <span style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: 36, height: 36, borderRadius: 'var(--radius-md)', background: tint, color: accent,
              }}>
                <Icon size={17} style={spin ? { animation: 'spin 1s linear infinite' } : undefined} />
              </span>
              <span style={{ fontSize: 13, color: 'var(--color-text-muted)', fontWeight: 500 }}>{label}</span>
              <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: -0.5 }}>
                {isLoading ? '···' : (value ?? 0)}
              </div>
            </div>
          </div>
        ))}
      </div>

      {processingDocs.length > 0 && (
        <div style={{
          marginBottom: 'var(--space-6)', padding: 'var(--space-4) var(--space-5)',
          background: '#ffffff', border: '1px solid #e2e8f0',
          borderLeft: '3px solid #fbbf24', borderRadius: 'var(--radius-md)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 13, fontWeight: 600, color: '#fbbf24', marginBottom: 'var(--space-3)' }}>
            <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
            처리 중인 작업 {processingDocs.length}건
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 320, overflowY: 'auto' }}>
            {processingDocs.map((doc) => (
              <div
                key={doc.id}
                className="row-link"
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  cursor: 'pointer', padding: 'var(--space-2) var(--space-2)',
                }}
                onClick={() => navigate(`/documents/${doc.id}`)}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 14 }}>
                  <span style={{
                    width: 6, height: 6, borderRadius: '50%', background: '#fbbf24',
                    animation: 'pulse-dot 1.4s ease-in-out infinite', flexShrink: 0,
                  }} />
                  {doc.original_filename}
                </span>
                <span className={`krds-badge xsmall ${STATUS_BADGE_CLASSES[doc.status] ?? 'bg-gray'}`}>
                  {STATUS_LABELS[doc.status] ?? doc.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!!projectsData?.items.length && (
        <div style={{ marginBottom: 'var(--space-6)' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 'var(--space-3)' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <FolderKanban size={14} /> 내 프로젝트
            </span>
            <button
              type="button"
              onClick={() => navigate('/projects')}
              style={{
                display: 'flex', alignItems: 'center', gap: 4, fontSize: 12,
                color: 'var(--color-text-muted)', background: 'none', border: 'none', cursor: 'pointer',
              }}
            >
              전체 보기 <ArrowRight size={12} />
            </button>
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-3)', overflowX: 'auto', paddingBottom: 4 }}>
            {projectsData.items.map((p) => (
              <div
                key={p.id}
                className="project-pill"
                onClick={() => navigate(`/projects/${p.id}`)}
                style={{
                  flex: '0 0 220px', cursor: 'pointer', padding: 'var(--space-3) var(--space-4)',
                  background: '#ffffff', border: '1px solid #e2e8f0',
                  borderRadius: 'var(--radius-md)',
                }}
              >
                <div style={{
                  fontSize: 14, fontWeight: 600, marginBottom: 4,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {p.name}
                </div>
                <div style={{ fontSize: 12, color: 'var(--color-text-muted)', display: 'flex', gap: 'var(--space-3)' }}>
                  <span>컬렉션 {p.collection_count}</span>
                  <span>멤버 {p.member_count}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(200px, 260px) minmax(320px, 1.3fr) minmax(280px, 1fr)', gap: 'var(--space-4)' }}>
        <div style={{
          padding: 'var(--space-4)', background: '#ffffff',
          border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)',
          display: 'flex', flexDirection: 'column', gap: 'var(--space-2)',
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 'var(--space-1)' }}>
            빠른 실행
          </div>
          {QUICK_LINKS.map(({ to, icon: Icon, label, desc }) => (
            <div
              key={to}
              className="quick-tile"
              onClick={() => navigate(to)}
              style={{
                display: 'flex', alignItems: 'center', gap: 'var(--space-3)', cursor: 'pointer',
                padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-md)',
                border: '1px solid transparent',
              }}
            >
              <span style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: 32, height: 32, borderRadius: 'var(--radius-md)',
                background: 'rgba(99,102,241,0.14)', color: '#4f46e5', flexShrink: 0,
              }}>
                <Icon size={15} />
              </span>
              <span style={{ minWidth: 0, flex: '1 1 auto' }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{label}</div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{desc}</div>
              </span>
              <ArrowRight size={13} className="quick-arrow" style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
            </div>
          ))}
        </div>

        <div style={{
          padding: 'var(--space-4)', background: '#ffffff',
          border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 13, fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 'var(--space-3)' }}>
            <FileText size={14} /> 최근 문서
          </div>
          {(recentDocs?.items.length ?? 0) === 0 && (
            <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>업로드된 문서가 없습니다.</p>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {recentDocs?.items.slice(0, 6).map((doc) => (
              <div
                key={doc.id}
                className="row-link"
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', padding: 'var(--space-2) var(--space-2)' }}
                onClick={() => navigate(`/documents/${doc.id}`)}
              >
                <span style={{ fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 'var(--space-2)' }}>
                  {doc.original_filename}
                </span>
                <span className={`krds-badge xsmall ${STATUS_BADGE_CLASSES[doc.status] ?? 'bg-gray'}`} style={{ flexShrink: 0 }}>
                  {STATUS_LABELS[doc.status] ?? doc.status}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div style={{
          padding: 'var(--space-4)', background: '#ffffff',
          border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 13, fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 'var(--space-3)' }}>
            <History size={14} /> 최근 검색
          </div>
          {(recentSearches?.items.length ?? 0) === 0 && (
            <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>검색 기록이 없습니다.</p>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {recentSearches?.items.map((h) => (
              <div
                key={h.id}
                className="row-link"
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', padding: 'var(--space-2) var(--space-2)' }}
                onClick={() => navigate('/search')}
              >
                <span style={{ fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 'var(--space-2)' }}>
                  {h.query}
                </span>
                <span style={{ fontSize: 12, color: 'var(--color-text-muted)', flexShrink: 0 }}>{h.result_count}건</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
