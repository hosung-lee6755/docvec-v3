import type { ReactNode } from 'react'
import { STATUS_LABELS } from '../../lib/documentStatus'
import { statusTone } from './classes'
import type { BadgeTone } from './classes'

interface BadgeProps {
  tone?: BadgeTone
  /** 점을 붙이면 색만이 아니라 모양으로도 상태가 구분된다 */
  hasDot?: boolean
  /** 표 안에서 바탕 없이 점과 글자만 */
  isPlain?: boolean
  className?: string
  title?: string
  children: ReactNode
}

export function Badge({ tone = 'neutral', hasDot = false, isPlain = false, className, title, children }: BadgeProps) {
  const classes = ['ds-badge', `ds-badge--${tone}`, isPlain ? 'ds-badge--plain' : '', className ?? '']
    .filter(Boolean)
    .join(' ')
  return (
    <span className={classes} title={title}>
      {hasDot && <span className="ds-badge__dot" aria-hidden="true" />}
      {children}
    </span>
  )
}

interface StatusBadgeProps {
  status: string
  label?: string
  isPlain?: boolean
}

/** 문서 처리 상태 배지. 글자는 STATUS_LABELS를 따른다. */
export function StatusBadge({ status, label, isPlain = false }: StatusBadgeProps) {
  return (
    <Badge tone={statusTone(status)} hasDot isPlain={isPlain}>
      {label ?? STATUS_LABELS[status] ?? status}
    </Badge>
  )
}

const LEVEL_CLASS: Record<string, string> = {
  public: 'ds-level--public',
  internal: 'ds-level--internal',
  confidential: 'ds-level--confidential',
}

interface SecurityLevelBadgeProps {
  level: string
  label: string
}

/** 보안등급 배지. 상태 색과 다른 계열을 쓴다. */
export function SecurityLevelBadge({ level, label }: SecurityLevelBadgeProps) {
  return <span className={`ds-level ${LEVEL_CLASS[level.toLowerCase()] ?? LEVEL_CLASS.public}`}>{label}</span>
}

interface CountBadgeProps {
  count: number
  tone?: 'neutral' | 'warning' | 'danger'
  label?: string
}

/** 메뉴 옆 건수. 0이면 그리지 않는다. */
export function CountBadge({ count, tone = 'neutral', label }: CountBadgeProps) {
  if (count <= 0) return null
  return (
    <span className={`ds-count ds-count--${tone}`} aria-label={label ? `${label} ${count}건` : undefined}>
      {count > 99 ? '99+' : count}
    </span>
  )
}
