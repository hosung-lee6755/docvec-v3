import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface ModalProps {
  isOpen: boolean
  title: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  size?: 'md' | 'lg' | 'xl'
  /** 바깥을 눌러도 닫히지 않게 할 때(입력 중인 폼 등) */
  isDismissible?: boolean
}

/** 대화상자. Esc로 닫고, 열릴 때 안으로 초점을 옮기고, 닫히면 원래 자리로 돌려준다. */
export function Modal({ isOpen, title, onClose, children, footer, size = 'md', isDismissible = true }: ModalProps) {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!isOpen) return undefined
    const previous = document.activeElement as HTMLElement | null
    const dialog = dialogRef.current
    // 닫기 단추보다 본문의 첫 입력에 먼저 초점을 둔다. 본문에 없으면 머리(닫기)로.
    const first = dialog?.querySelector<HTMLElement>(`.ds-modal__body :is(${FOCUSABLE})`)
      ?? dialog?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? dialog)?.focus()

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !dialog) return
      const nodes = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (nodes.length === 0) return
      const head = nodes[0]
      const tail = nodes[nodes.length - 1]
      if (event.shiftKey && document.activeElement === head) {
        event.preventDefault()
        tail.focus()
      } else if (!event.shiftKey && document.activeElement === tail) {
        event.preventDefault()
        head.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      previous?.focus?.()
    }
  }, [isOpen])

  if (!isOpen) return null

  const sizeClass = size === 'md' ? '' : ` ds-modal--${size}`
  return createPortal(
    <div
      className="ds-modal-backdrop"
      onMouseDown={(event) => {
        if (isDismissible && event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={dialogRef}
        className={`ds-modal${sizeClass}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className="ds-modal__header">
          <h2 id={titleId} className="ds-modal__title">{title}</h2>
          <button type="button" className="ds-icon-btn" aria-label="닫기" title="닫기" onClick={onClose}>
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="ds-modal__body">{children}</div>
        {footer && <div className="ds-modal__footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
