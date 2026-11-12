import type { KeyboardEvent, ReactNode } from 'react'

export type StatTone = 'default' | 'warning' | 'danger' | 'success'

interface StatProps {
  label: ReactNode
  value: ReactNode
  hint?: ReactNode
  tone?: StatTone
  /** 누르면 해당 조건으로 거른다. 없으면 단순 표시 */
  onClick?: () => void
  isActive?: boolean
}

/** 요약 띠의 칸 하나. 누를 수 있으면 button으로 그린다. */
export function Stat({ label, value, hint, tone = 'default', onClick, isActive }: StatProps) {
  const classes = ['ds-stat', tone === 'default' ? '' : `ds-stat--${tone}`].filter(Boolean).join(' ')
  const body = (
    <>
      <div className="ds-stat__label">{label}</div>
      <div className="ds-stat__value">
        {value}
        {hint && <span className="ds-stat__hint">{hint}</span>}
      </div>
    </>
  )
  if (!onClick) return <div className={classes}>{body}</div>
  return (
    <button type="button" className={classes} onClick={onClick} aria-pressed={isActive}>
      {body}
    </button>
  )
}

interface StatStripProps {
  children: ReactNode
  label?: string
}

/** 관리 화면 머리 아래의 요약 띠. 지금 있는 API 값만 보여 준다. */
export function StatStrip({ children, label = '요약' }: StatStripProps) {
  return (
    <section className="ds-stat-strip" aria-label={label}>
      {children}
    </section>
  )
}

interface BulkActionBarProps {
  count: number
  onClear: () => void
  children: ReactNode
}

/** 표에서 여러 행을 골랐을 때만 나타나는 일괄 작업 막대. */
export function BulkActionBar({ count, onClear, children }: BulkActionBarProps) {
  if (count <= 0) return null
  return (
    <div className="ds-bulk-bar" role="region" aria-label="선택한 항목 일괄 작업">
      <span className="ds-bulk-bar__count" aria-live="polite">{count}개 선택</span>
      {children}
      <span className="ds-bulk-bar__spacer" />
      <button type="button" onClick={onClear}>선택 해제</button>
    </div>
  )
}

interface SplitProps {
  main: ReactNode
  panel?: ReactNode
}

/** 목록과 옆 패널을 나란히 둔다. 좁으면 패널이 아래로 내려간다. */
export function Split({ main, panel }: SplitProps) {
  return (
    <div className="ds-split">
      <div className="ds-split__main">{main}</div>
      {panel}
    </div>
  )
}

interface SidePanelProps {
  eyebrow?: ReactNode
  title: ReactNode
  actions?: ReactNode
  children: ReactNode
  label?: string
}

export function SidePanel({ eyebrow, title, actions, children, label }: SidePanelProps) {
  return (
    <aside className="ds-side-panel" aria-label={label}>
      <div>
        {eyebrow && <div className="ds-side-panel__eyebrow">{eyebrow}</div>}
        <h2 className="ds-side-panel__title">{title}</h2>
      </div>
      {children}
      {actions}
    </aside>
  )
}

export interface DescriptionItem {
  term: ReactNode
  detail: ReactNode
  key: string
}

export function DescriptionList({ items }: { items: ReadonlyArray<DescriptionItem> }) {
  return (
    <dl className="ds-dl">
      {items.map((item) => (
        <div key={item.key} style={{ display: 'contents' }}>
          <dt>{item.term}</dt>
          <dd>{item.detail}</dd>
        </div>
      ))}
    </dl>
  )
}

export interface TabItem<T extends string> {
  value: T
  label: ReactNode
}

interface TabsProps<T extends string> {
  items: ReadonlyArray<TabItem<T>>
  value: T
  onChange: (value: T) => void
  label: string
  /** 탭 패널 id 접두. 패널 쪽은 `${idPrefix}-panel-${value}`를 쓴다 */
  idPrefix: string
}

/** 화살표 키로 옮겨 다니는 탭 목록(WAI-ARIA tabs). */
export function Tabs<T extends string>({ items, value, onChange, label, idPrefix }: TabsProps<T>) {
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (step === 0) return
    event.preventDefault()
    const index = items.findIndex((item) => item.value === value)
    const next = items[(index + step + items.length) % items.length]
    onChange(next.value)
    document.getElementById(`${idPrefix}-tab-${next.value}`)?.focus()
  }
  return (
    <div className="ds-tabs" role="tablist" aria-label={label} onKeyDown={handleKeyDown}>
      {items.map((item) => {
        const isSelected = item.value === value
        return (
          <button
            key={item.value}
            id={`${idPrefix}-tab-${item.value}`}
            type="button"
            role="tab"
            className="ds-tab"
            aria-selected={isSelected}
            aria-controls={`${idPrefix}-panel-${item.value}`}
            tabIndex={isSelected ? 0 : -1}
            onClick={() => onChange(item.value)}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
