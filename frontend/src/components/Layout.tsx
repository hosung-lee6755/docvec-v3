import { useEffect, useState } from 'react'
// NavLink는 쿼리를 무시하고 aria-current를 스스로 붙이므로 Link에 직접 계산한 값을 준다.
import { Outlet, Link, useLocation } from 'react-router-dom'
import { LogOut, Menu, Search, Settings, X } from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import { useWaitingReviewCount, useFailedCount } from '../hooks/useDocuments'
import { CountBadge } from './ui'
import { CommandPalette } from './CommandPalette'
import { HOME_ITEM, isNavItemActive, visibleNavGroups } from './navigation'
import type { NavItem } from './navigation'

function initialOf(email: string | undefined): string {
  return (email ?? '?').trim().charAt(0).toUpperCase() || '?'
}

export default function Layout() {
  const clearAuth = useAuthStore((s) => s.clearAuth)
  const user = useAuthStore((s) => s.user)
  const waitingReviewCount = useWaitingReviewCount()
  const failedCount = useFailedCount()
  const location = useLocation()
  const [isPaletteOpen, setIsPaletteOpen] = useState(false)
  // 좁은 화면(860px 이하)에서만 쓰는 메뉴 펼침 상태. 화면을 옮기면 접는다.
  const [isNavOpen, setIsNavOpen] = useState(false)
  const isAdmin = user?.role === 'admin'

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setIsPaletteOpen((open) => !open)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  useEffect(() => {
    setIsNavOpen(false)
  }, [location.pathname, location.search])

  const renderItem = ({ to, icon: Icon, label, badge }: NavItem) => {
    const isActive = isNavItemActive(location.pathname, location.search, to)
    return (
      <Link key={to} to={to} className="ds-nav__item" aria-current={isActive ? 'page' : undefined}>
        <Icon size={16} aria-hidden="true" />
        <span className="ds-nav__label">{label}</span>
        {badge === 'waitingReview' && <CountBadge count={waitingReviewCount} tone="warning" label="검토 대기" />}
        {badge === 'failed' && <CountBadge count={failedCount} tone="danger" label="실패" />}
      </Link>
    )
  }

  const isSettingsActive = location.pathname === '/settings'

  return (
    <div className="ds-shell">
      <nav className="ds-sidebar" aria-label="주 메뉴">
        <div className="ds-sidebar__brand">
          <span className="ds-sidebar__logo" aria-hidden="true">DV</span>
          <span className="ds-sidebar__product">
            <strong>DocVec</strong>
            <span>문서 지식 플랫폼</span>
          </span>
          <button
            type="button"
            className="ds-icon-btn ds-sidebar__toggle"
            aria-label={isNavOpen ? '메뉴 닫기' : '메뉴 열기'}
            aria-expanded={isNavOpen}
            aria-controls="ds-sidebar-body"
            onClick={() => setIsNavOpen((open) => !open)}
          >
            {isNavOpen ? <X size={16} aria-hidden="true" /> : <Menu size={16} aria-hidden="true" />}
          </button>
        </div>

        <div id="ds-sidebar-body" className={`ds-sidebar__body${isNavOpen ? ' is-open' : ''}`}>
        <button type="button" className="ds-sidebar__find" onClick={() => setIsPaletteOpen(true)}>
          <Search size={14} aria-hidden="true" />
          <span style={{ flex: 1 }}>화면 찾기</span>
          <kbd className="ds-kbd">Ctrl K</kbd>
        </button>

        <div className="ds-nav">{renderItem(HOME_ITEM)}</div>

        {visibleNavGroups(isAdmin).map((group) => (
          <div key={group.section} className="ds-nav" role="group" aria-label={group.section}>
            <div className="ds-nav__section" aria-hidden="true">{group.section}</div>
            {group.items.map(renderItem)}
          </div>
        ))}

        <div className="ds-sidebar__footer">
          <div className="ds-user">
            <span className="ds-avatar" aria-hidden="true">{initialOf(user?.email)}</span>
            <span className="ds-user__name" title={user?.email}>{user?.email}</span>
            <Link
              to="/settings"
              title="계정 설정"
              aria-label="계정 설정"
              className="ds-icon-btn"
              aria-current={isSettingsActive ? 'page' : undefined}
            >
              <Settings size={15} aria-hidden="true" />
            </Link>
          </div>
          <button type="button" onClick={clearAuth} className="ds-nav__item" style={{ border: 0, background: 'transparent', cursor: 'pointer', font: 'inherit' }}>
            <LogOut size={16} aria-hidden="true" />
            <span className="ds-nav__label" style={{ textAlign: 'left' }}>로그아웃</span>
          </button>
        </div>
        </div>
      </nav>

      <main className="ds-main">
        <div className="ds-main__frame">
          <Outlet />
        </div>
      </main>

      <CommandPalette isOpen={isPaletteOpen} isAdmin={isAdmin} onClose={() => setIsPaletteOpen(false)} />
    </div>
  )
}
