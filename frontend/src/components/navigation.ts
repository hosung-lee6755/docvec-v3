import { LayoutDashboard, FileText, FolderKanban, FolderOpen, Search, Users, MessageSquare, ScrollText, DollarSign, BookOpen, GitBranch, AlertTriangle, XCircle, Activity, Eraser, ShieldCheck, Route, FileCheck, HardDrive, Plug, Settings } from 'lucide-react'

export interface NavItem {
  to: string
  icon: typeof FileText
  label: string
  badge?: 'waitingReview' | 'failed'
  adminOnly?: boolean
}

export interface NavGroup {
  section: string
  adminOnly?: boolean
  items: NavItem[]
}

export const HOME_ITEM: NavItem = { to: '/', icon: LayoutDashboard, label: '대시보드' }
export const SETTINGS_ITEM: NavItem = { to: '/settings', icon: Settings, label: '계정 설정' }

// 정보 구조: 탐색 단위(워크스페이스)를 맨 위에 두고, 매일 쓰는 업무(문서 처리, 지식 활용)와
// 가끔 손대는 기술 설정(파이프라인 설정)을 나눈다. 관리 그룹은 관리자에게만 보인다.
export const NAV_GROUPS: NavGroup[] = [
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
      { to: '/connectors', icon: HardDrive, label: '문서 원천 연결' },
      { to: '/access-tokens', icon: Plug, label: '외부 에이전트 토큰' },
      { to: '/audit-logs', icon: ScrollText, label: '감사 로그' },
      { to: '/answer-traces', icon: Route, label: '답변 추적' },
      { to: '/governance-report', icon: FileCheck, label: 'AI 기본법 근거 자료' },
      { to: '/usage', icon: DollarSign, label: '사용량' },
    ],
  },
]

/** 역할에 맞게 보이는 그룹과 항목만 남긴다. */
export function visibleNavGroups(isAdmin: boolean): NavGroup[] {
  return NAV_GROUPS
    .filter((group) => isAdmin || !group.adminOnly)
    .map((group) => ({ ...group, items: group.items.filter((item) => isAdmin || !item.adminOnly) }))
}

// React Router의 NavLink는 경로만 비교하므로 "/documents"와 "/documents?status=..."가
// 함께 켜진다. 쿼리까지 비교해 하나만 켜지게 한다.
export function isNavItemActive(pathname: string, search: string, to: string): boolean {
  const [toPath, toQuery] = to.split('?')
  if (toPath === '/') return pathname === '/'
  if (pathname !== toPath && !pathname.startsWith(`${toPath}/`)) return false
  if (toQuery) return search === `?${toQuery}`
  return search !== '?status=WAITING_REVIEW' && search !== '?status=FAILED'
}
