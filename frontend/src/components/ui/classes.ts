import { STATUS_BADGE_CLASSES } from '../../lib/documentStatus'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-solid'
export type ButtonSize = 'sm' | 'md' | 'lg'
export type BadgeTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'outline'

/** 버튼 모양 클래스. Link처럼 button이 아닌 요소를 버튼 모양으로 그릴 때도 쓴다. */
export function buttonClass(variant: ButtonVariant = 'secondary', size: ButtonSize = 'md', extra = ''): string {
  const sizeClass = size === 'md' ? '' : ` ds-btn--${size}`
  return `ds-btn ds-btn--${variant}${sizeClass}${extra ? ` ${extra}` : ''}`
}

const KRDS_CLASS_TO_TONE: Record<string, BadgeTone> = {
  'bg-gray': 'neutral',
  'bg-success': 'success',
  'bg-danger': 'danger',
  'bg-information': 'info',
  'bg-warning': 'warning',
}

/** 예전 KRDS 배지 클래스(bg-success 등)를 배지 색조로 바꾼다. 헬퍼가 bg-* 문자열을 돌려줄 때 쓴다. */
export function toneFromKrdsClass(krdsClass: string | undefined): BadgeTone {
  const key = (krdsClass ?? '').split(/\s+/).find((part) => part.startsWith('bg-')) ?? ''
  return KRDS_CLASS_TO_TONE[key] ?? 'neutral'
}

/** 문서 처리 상태를 배지 색조로 바꾼다. */
export function statusTone(status: string): BadgeTone {
  return toneFromKrdsClass(STATUS_BADGE_CLASSES[status])
}
