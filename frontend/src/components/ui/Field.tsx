import { forwardRef, useId } from 'react'
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { Search } from 'lucide-react'

interface FieldProps {
  label: ReactNode
  hint?: ReactNode
  error?: ReactNode
  /** 입력 요소를 받는다. id를 넘기면 label과 이어 준다 */
  children: (id: string) => ReactNode
  className?: string
}

/** 라벨, 도움말, 오류를 입력 요소와 이어 주는 틀. */
export function Field({ label, hint, error, children, className }: FieldProps) {
  const id = useId()
  return (
    <div className={['ds-field', className ?? ''].filter(Boolean).join(' ')}>
      <label className="ds-field__label" htmlFor={id}>{label}</label>
      {children(id)}
      {hint && !error && <span className="ds-field__hint">{hint}</span>}
      {error && <span className="ds-field__error" role="alert">{error}</span>}
    </div>
  )
}

type ControlSize = 'sm' | 'md'

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  controlSize?: ControlSize
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ controlSize = 'md', className, ...rest }, ref) {
  const classes = ['ds-input', controlSize === 'sm' ? 'ds-input--sm' : '', className ?? ''].filter(Boolean).join(' ')
  return <input ref={ref} className={classes} {...rest} />
})

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  controlSize?: ControlSize
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { controlSize = 'md', className, children, ...rest },
  ref,
) {
  const classes = ['ds-select', controlSize === 'sm' ? 'ds-select--sm' : '', className ?? ''].filter(Boolean).join(' ')
  return <select ref={ref} className={classes} {...rest}>{children}</select>
})

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...rest },
  ref,
) {
  return <textarea ref={ref} className={['ds-textarea', className ?? ''].filter(Boolean).join(' ')} {...rest} />
})

export interface SearchInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  /** 보이는 라벨이 없으므로 접근성 이름이 필요하다 */
  label: string
  width?: number | string
}

/** 돋보기가 붙은 거르기 입력. */
export function SearchInput({ label, width = 260, placeholder, ...rest }: SearchInputProps) {
  return (
    <label className="ds-search" style={{ flex: `0 1 ${typeof width === 'number' ? `${width}px` : width}` }}>
      <Search size={14} aria-hidden="true" />
      <input type="search" aria-label={label} placeholder={placeholder ?? label} {...rest} />
    </label>
  )
}
