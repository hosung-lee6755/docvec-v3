import { createContext, useContext } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'

// 화면 안에 화면이 들어가는 경우(프로젝트 > 워크스페이스 > 컬렉션 등) 안쪽 머리는 h2로 낮춘다.
// 그래야 한 화면에 h1이 하나만 남는다.
const PageDepthContext = createContext(0)

function cx(...parts: Array<string | false | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

interface PageHeaderProps {
  title: ReactNode
  subtitle?: ReactNode
  /** 제목 위 빵부스러기 */
  breadcrumb?: ReactNode
  actions?: ReactNode
}

/** 화면 머리. 제목은 화면마다 h1 하나다. */
export function PageHeader({ title, subtitle, breadcrumb, actions }: PageHeaderProps) {
  const isNested = useContext(PageDepthContext) > 1
  const Heading = isNested ? 'h2' : 'h1'
  return (
    <header className={cx('ds-page-header', isNested && 'ds-page-header--nested')}>
      <div className="ds-page-header__titles">
        {breadcrumb && <nav className="ds-breadcrumb" aria-label="위치">{breadcrumb}</nav>}
        <Heading className="ds-page-header__title">{title}</Heading>
        {subtitle && <p className="ds-page-header__subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="ds-page-header__actions">{actions}</div>}
    </header>
  )
}

/** PageHeader 없이 제목을 직접 그리는 화면(채팅 시작 등)용. 겹친 화면 안이면 h2가 된다. */
export function PageTitle({ children, className }: { children: ReactNode; className?: string }) {
  const Heading = useContext(PageDepthContext) > 1 ? 'h2' : 'h1'
  return <Heading className={className}>{children}</Heading>
}

interface BoxProps {
  children: ReactNode
  className?: string
}

export function Page({ children, className }: BoxProps) {
  const depth = useContext(PageDepthContext)
  return (
    <PageDepthContext.Provider value={depth + 1}>
      <div className={cx('ds-page', depth > 0 && 'ds-page--nested', className)}>{children}</div>
    </PageDepthContext.Provider>
  )
}

export function PageBody({ children, className }: BoxProps) {
  return <div className={cx('ds-page-body', className)}>{children}</div>
}

interface CardProps extends BoxProps {
  title?: ReactNode
  actions?: ReactNode
  /** 몸통 안쪽 여백을 빼고 표 같은 것을 끝까지 붙일 때 */
  isFlush?: boolean
}

export function Card({ title, actions, isFlush = false, children, className }: CardProps) {
  return (
    <section className={cx('ds-card', className)}>
      {(title || actions) && (
        <div className="ds-card__header">
          {title && <h2 className="ds-card__title">{title}</h2>}
          {actions}
        </div>
      )}
      {isFlush ? children : <div className="ds-card__body">{children}</div>}
    </section>
  )
}

interface ToolbarProps extends Omit<BoxProps, 'children'> {
  children?: ReactNode
  /** 오른쪽 끝에 붙는 건수 같은 정보 */
  meta?: ReactNode
  label?: string
}

export function Toolbar({ children, meta, label, className }: ToolbarProps) {
  return (
    <div className={cx('ds-toolbar', className)} role="toolbar" aria-label={label}>
      {children}
      {meta && (
        <>
          <span className="ds-toolbar__spacer" />
          <span className="ds-toolbar__meta">{meta}</span>
        </>
      )}
    </div>
  )
}

interface FilterChipProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  isActive: boolean
}

/** 눌린 상태를 aria-pressed로 알리는 거르기 단추. */
export function FilterChip({ isActive, className, children, ...rest }: FilterChipProps) {
  return (
    <button type="button" aria-pressed={isActive} className={cx('ds-chip', className)} {...rest}>
      {children}
    </button>
  )
}

interface SegmentedOption<T extends string> {
  value: T
  label: ReactNode
}

interface SegmentedProps<T extends string> {
  options: ReadonlyArray<SegmentedOption<T>>
  value: T
  onChange: (value: T) => void
  label: string
}

export function Segmented<T extends string>({ options, value, onChange, label }: SegmentedProps<T>) {
  return (
    <div className="ds-segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

interface EmptyStateProps {
  title: ReactNode
  description?: ReactNode
  icon?: ReactNode
  action?: ReactNode
}

export function EmptyState({ title, description, icon, action }: EmptyStateProps) {
  return (
    <div className="ds-empty">
      {icon}
      <div className="ds-empty__title">{title}</div>
      {description && <div className="ds-empty__desc">{description}</div>}
      {action}
    </div>
  )
}

type AlertTone = 'info' | 'success' | 'warning' | 'danger'

const ALERT_ICON: Record<AlertTone, typeof Info> = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
}

interface AlertProps extends BoxProps {
  tone?: AlertTone
}

/** 알림 상자. 위험과 경고는 화면 낭독기가 바로 읽도록 role=alert를 준다. */
export function Alert({ tone = 'info', children, className }: AlertProps) {
  const Icon = ALERT_ICON[tone]
  const role = tone === 'danger' || tone === 'warning' ? 'alert' : 'status'
  return (
    <div className={cx('ds-alert', `ds-alert--${tone}`, className)} role={role}>
      <Icon size={16} aria-hidden="true" style={{ flexShrink: 0, marginTop: 2 }} />
      <div style={{ minWidth: 0, flex: 1 }}>{children}</div>
    </div>
  )
}
