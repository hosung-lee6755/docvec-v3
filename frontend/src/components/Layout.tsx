import { Outlet, NavLink } from 'react-router-dom'
import { LayoutDashboard, FileText, FolderKanban, FolderOpen, Search, LogOut, Users, MessageSquare, Settings, ScrollText, DollarSign, BookOpen, GitBranch } from 'lucide-react'
import { useAuthStore } from '../store/authStore'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: '대시보드', end: true },
  { to: '/projects', icon: FolderKanban, label: '프로젝트' },
  { to: '/collections', icon: FolderOpen, label: '컬렉션' },
  { to: '/documents', icon: FileText, label: '문서' },
  { to: '/search', icon: Search, label: '검색' },
  { to: '/chat', icon: MessageSquare, label: '채팅' },
  { to: '/workflows', icon: GitBranch, label: '워크플로우' },
  { to: '/users', icon: Users, label: '사용자', adminOnly: true },
  { to: '/audit-logs', icon: ScrollText, label: '감사 로그', adminOnly: true },
  { to: '/usage', icon: DollarSign, label: '사용량', adminOnly: true },
  { to: '/dictionary', icon: BookOpen, label: '검색 사전', adminOnly: true },
]

export default function Layout() {
  const clearAuth = useAuthStore((s) => s.clearAuth)
  const user = useAuthStore((s) => s.user)

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
      }}>
        <div style={{ padding: 'var(--space-4) var(--space-2)', marginBottom: 'var(--space-4)' }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--color-accent)' }}>DocVec</span>
        </div>
        {navItems.filter(({ adminOnly }) => !adminOnly || user?.role === 'admin').map(({ to, icon: Icon, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
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
              transition: 'all var(--duration-fast)',
            })}
          >
            <Icon size={16} />
            {label}
          </NavLink>
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
