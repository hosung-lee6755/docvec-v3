import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Bell, ClipboardCheck, MessageSquare, ServerCrash, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  useDeleteNotification,
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from '../hooks/useNotifications'
import type { AppNotification, NotificationKind } from '../hooks/useNotifications'
import { formatElapsed } from '../lib/elapsedTime'

// 전체 점검 2-7 — 사이드바 아래쪽의 알림 단추. 누르면 최근 알림 목록이 열린다.

const KIND_VIEW: Record<NotificationKind, { icon: LucideIcon; tone: 'danger' | 'warning' }> = {
  document_failed: { icon: AlertTriangle, tone: 'danger' },
  review_waiting: { icon: ClipboardCheck, tone: 'warning' },
  sync_failed: { icon: ServerCrash, tone: 'danger' },
  inquiry_created: { icon: MessageSquare, tone: 'warning' },
  inquiry_replied: { icon: MessageSquare, tone: 'warning' },
  inquiry_followup: { icon: MessageSquare, tone: 'warning' },
}

export function NotificationBell() {
  const [isOpen, setIsOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  // 패널은 body에 그린다. 사이드바 안에 두면 스크롤 영역에 잘리고 본문 틀에 가려진다
  const panelRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const { data, isError } = useNotifications()
  const markRead = useMarkNotificationRead()
  const markAllRead = useMarkAllNotificationsRead()
  const remove = useDeleteNotification()
  const items = data?.items ?? []
  const unreadCount = data?.unread_count ?? 0

  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsOpen(false)
    }
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node
      if (rootRef.current?.contains(target) || panelRef.current?.contains(target)) return
      setIsOpen(false)
    }
    document.addEventListener('keydown', handleKeyDown)
    document.addEventListener('mousedown', handlePointerDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.removeEventListener('mousedown', handlePointerDown)
    }
  }, [isOpen])

  const open = (item: AppNotification) => {
    if (!item.read_at) markRead.mutate(item.id)
    setIsOpen(false)
    if (item.link) navigate(item.link)
  }

  return (
    <div className="ds-notify" ref={rootRef}>
      <button
        type="button"
        className="ds-icon-btn ds-notify__trigger"
        aria-label={unreadCount > 0 ? `알림, 읽지 않은 알림 ${unreadCount}건` : '알림'}
        aria-expanded={isOpen}
        aria-haspopup="dialog"
        title="알림"
        onClick={() => setIsOpen((value) => !value)}
      >
        <Bell size={15} aria-hidden="true" />
        {unreadCount > 0 && (
          <span className="ds-notify__dot" aria-hidden="true">{unreadCount > 9 ? '9+' : unreadCount}</span>
        )}
      </button>

      {isOpen && createPortal(
        <div className="ds-notify__panel" role="dialog" aria-label="알림" ref={panelRef}>
          <div className="ds-notify__head">
            <strong>알림</strong>
            <button
              type="button"
              className="ds-notify__all"
              disabled={unreadCount === 0 || markAllRead.isPending}
              onClick={() => markAllRead.mutate()}
            >
              모두 읽음으로 표시
            </button>
          </div>
          {isError && (
            <p className="ds-notify__empty" role="alert">알림을 불러오지 못했습니다. 잠시 뒤 다시 열어 주세요.</p>
          )}
          {!isError && items.length === 0 && <p className="ds-notify__empty">새 알림이 없습니다.</p>}
          <ul className="ds-notify__list">
            {items.map((item) => {
              const view = KIND_VIEW[item.kind] ?? KIND_VIEW.document_failed
              const Icon = view.icon
              return (
                <li key={item.id} className={`ds-notify__item${item.read_at ? '' : ' is-unread'}`}>
                  <button type="button" className="ds-notify__open" onClick={() => open(item)}>
                    <span className={`ds-notify__icon ds-notify__icon--${view.tone}`} aria-hidden="true">
                      <Icon size={14} />
                    </span>
                    <span className="ds-notify__text">
                      <span className="ds-notify__title">{item.title}</span>
                      {item.body && <span className="ds-notify__body">{item.body}</span>}
                      <span className="ds-notify__time">{formatElapsed(item.created_at)}</span>
                    </span>
                  </button>
                  <button
                    type="button"
                    className="ds-icon-btn ds-notify__remove"
                    aria-label={`알림 지우기: ${item.title}`}
                    title="지우기"
                    onClick={() => remove.mutate(item.id)}
                  >
                    <X size={13} aria-hidden="true" />
                  </button>
                </li>
              )
            })}
          </ul>
        </div>,
        document.body,
      )}
    </div>
  )
}
