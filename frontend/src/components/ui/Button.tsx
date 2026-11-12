import { forwardRef } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { buttonClass } from './classes'
import type { ButtonSize, ButtonVariant } from './classes'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: ReactNode
  isBlock?: boolean
}

/** 기본 버튼. type은 기본 button이다(폼 안에서 뜻하지 않게 제출되지 않게). */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon, isBlock = false, className, type = 'button', children, ...rest },
  ref,
) {
  const extra = [isBlock ? 'ds-btn--block' : '', className ?? ''].filter(Boolean).join(' ')
  return (
    <button ref={ref} type={type} className={buttonClass(variant, size, extra)} {...rest}>
      {icon}
      {children}
    </button>
  )
})

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** 화면 낭독기가 읽는 이름. 글자가 없는 버튼이라 반드시 필요하다 */
  label: string
  tone?: 'default' | 'danger'
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, tone = 'default', className, type = 'button', title, children, ...rest },
  ref,
) {
  const classes = ['ds-icon-btn', tone === 'danger' ? 'ds-icon-btn--danger' : '', className ?? ''].filter(Boolean).join(' ')
  return (
    <button ref={ref} type={type} aria-label={label} title={title ?? label} className={classes} {...rest}>
      {children}
    </button>
  )
})
