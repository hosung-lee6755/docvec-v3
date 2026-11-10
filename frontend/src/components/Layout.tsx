import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { LayoutDashboard, FileText, FolderKanban, FolderOpen, Search, LogOut, Users, MessageSquare, Settings, ScrollText, DollarSign, BookOpen, GitBranch, AlertTriangle, XCircle, Activity, Eraser, ShieldCheck } from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import { useWaitingReviewCount, useFailedCount } from '../hooks/useDocuments'

interface NavItem {
  to: string
  icon: typeof FileText
  label: string
  badge?: 'waitingReview' | 'failed'
  adminOnly?: boolean
}

interface NavGroup {
  section: string
  adminOnly?: boolean
  items: NavItem[]
}

// 정보 구조: 탐색 단위(워크스페이스)를 최상단으로 승격하고, 매일 쓰는 업무(문서 처리/
// 지식 활용)와 가끔 손대는 기술 설정(파이프라인 설정)을 분리 — 기존 "구성" 그룹이 이
// 둘을 한데 묶어 프로젝트가 3번째 그룹에 묻혀 있던 문제를 해소한다.
const navGroups: NavGroup[] = [
  {
    section: '워크스페이스',
    items: [
      { to: '/projects', icon: FolderKanban, label: '프로젝트' },
      { to: '/collections', icon: FolderOpen, label: '컬렉션' },
    ],
  },
  {
    section: '문서 처리',
    items: [
      { to: '/documents', icon: FileText, label: '문서' },
      { to: '/documents?status=WAITING_REVIEW', icon: AlertTriangle, label: '검토 대기', badge: 'waitingReview' },
      { to: '/documents?status=FAILED', icon: XCircle, label: '실패', badge: 'failed' },
      { to: '/processing-status', icon: Activity, label: '처리 현황' },
    ],
  },
  {
    section: '지식 활용',
    items: [
      { to: '/search', icon: Search, label: '검색' },
      { to: '/chat', icon: MessageSquare, label: '채팅' },
    ],
  },
  {
    section: '파이프라인 설정',
    items: [
      { to: '/workflows', icon: GitBranch, label: '워크플로우' },
      { to: '/dictionary', icon: BookOpen, label: '검색 사전', adminOnly: true },
      { to: '/cleaning-rules', icon: Eraser, label: '정제 규칙', adminOnly: true },
    ],
  },
  {
    section: '관리',
    adminOnly: true,
    items: [
      { to: '/users', icon: Users, label: '사용자' },
      { to: '/groups', icon: ShieldCheck, label: '그룹' },
      { to: '/audit-logs', icon: ScrollText, label: '감사 로그' },
      { to: '/usage', icon: DollarSign, label: '사용량' },
    ],
  },
]

// React Router's NavLink only matches on pathname, so "/documents" and
// "/documents?status=WAITING_REVIEW" (같은 pathname, 다른 쿼리) both light up
// together — this compares the query string too so only one is active.
function isNavItemActive(pathname: string, search: string, to: string): boolean {
  const [toPath, toQuery] = to.split('?')
  if (pathname !== toPath && !pathname.startsWith(`${toPath}/`)) return false
  if (toQuery) return search === `?${toQuery}`
  return search !== '?status=WAITING_REVIEW' && search !== '?status=FAILED'
}

export default function Layout() {
  const clearAuth = useAuthStore((s) => s.clearAuth)
  const user = useAuthStore((s) => s.user)
  const waitingReviewCount = useWaitingReviewCount()
  const failedCount = useFailedCount()
  const location = useLocation()

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <nav style={{
        width: 220,
        background: 'var(--color-surface)',
        borderRight: '1px solid var(--color-border)',
        display: 'flex',
        flexDirection: 'column',
        padding: 'var(--space-4)',
        gap: 'var(--space-1)',
        flexShrink: 0,
        overflowY: 'auto',
      }}>
        <div style={{ padding: 'var(--space-4) var(--space-2)', marginBottom: 'var(--space-4)' }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-accent)' }}>DocVec</span>
        </div>
        <NavLink
          to="/"
          end
          style={({ isActive }) => ({
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-3)',
            padding: 'var(--space-2) var(--space-3)',
            borderRadius: 'var(--radius-md)',
            color: isActive ? 'var(--color-text)' : 'var(--color-text-muted)',
            background: isActive ? 'rgba(99,102,241,0.15)' : 'transparent',
            textDecoration: 'none',
            fontSize: 14,
            marginBottom: 'var(--space-2)',
            transition: 'all var(--duration-fast)',
          })}
        >
          <LayoutDashboard size={16} />
          대시보드
        </NavLink>
        {navGroups
          .filter((group) => !group.adminOnly || user?.role === 'admin')
          .map((group) => (
            <div key={group.section} style={{ marginTop: 'var(--space-3)' }}>
              <div style={{
                padding: 'var(--space-1) var(--space-3)',
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
                color: 'var(--color-text-muted)',
                opacity: 0.7,
              }}>
                {group.section}
              </div>
              {group.items
                .filter((item) => !item.adminOnly || user?.role === 'admin')
                .map(({ to, icon: Icon, label, badge }) => {
                  const active = isNavItemActive(location.pathname, location.search, to)
                  return (
                    <NavLink
                      key={to}
                      to={to}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-3)',
                        padding: 'var(--space-2) var(--space-3)',
                        borderRadius: 'var(--radius-md)',
                        color: active ? 'var(--color-text)' : 'var(--color-text-muted)',
                        background: active ? 'rgba(99,102,241,0.15)' : 'transparent',
                        textDecoration: 'none',
                        fontSize: 14,
                        transition: 'all var(--duration-fast)',
                      }}
                    >
                      <Icon size={16} />
                      <span style={{ flex: 1 }}>{label}</span>
                      {badge === 'waitingReview' && waitingReviewCount > 0 && (
                        <span className="krds-badge xsmall bg-warning">{waitingReviewCount}</span>
                      )}
                      {badge === 'failed' && failedCount > 0 && (
                        <span className="krds-badge xsmall bg-danger">{failedCount}</span>
                      )}
                    </NavLink>
                  )
                })}
            </div>
          ))}
        <div style={{ marginTop: 'auto' }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: 'var(--space-2) var(--space-3)', gap: 'var(--space-2)',
          }}>
            <span style={{
              color: 'var(--color-text-muted)', fontSize: 12,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {user?.email}
            </span>
            <NavLink
              to="/settings"
              title="계정 설정"
              aria-label="계정 설정"
              style={({ isActive }) => ({
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexShrink: 0, width: 24, height: 24, borderRadius: 'var(--radius-md, 6px)',
                color: isActive ? 'var(--color-text)' : 'var(--color-text-muted)',
                background: isActive ? 'rgba(99,102,241,0.15)' : 'transparent',
              })}
            >
              <Settings size={14} />
            </NavLink>
          </div>
          <button
            type="button"
            onClick={clearAuth}
            className="krds-btn medium text"
            style={{
              width: '100%', display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-start',
              gap: 'var(--space-3)', fontSize: 14, color: 'var(--color-text-muted)',
            }}
          >
            <LogOut size={16} />
            로그아웃
          </button>
        </div>
      </nav>
      <main style={{ flex: 1, overflow: 'auto', padding: 'var(--space-8)' }}>
        <Outlet />
      </main>
    </div>
  )
}
