import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { HOME_ITEM, SETTINGS_ITEM, visibleNavGroups } from './navigation'
import type { NavItem } from './navigation'

interface PaletteEntry {
  item: NavItem
  group: string
}

interface CommandPaletteProps {
  isOpen: boolean
  isAdmin: boolean
  onClose: () => void
}

function buildEntries(isAdmin: boolean): PaletteEntry[] {
  const groups = visibleNavGroups(isAdmin)
  return [
    { item: HOME_ITEM, group: '바로가기' },
    ...groups.flatMap((group) => group.items.map((item) => ({ item, group: group.section }))),
    { item: SETTINGS_ITEM, group: '계정' },
  ]
}

/** Ctrl K로 여는 화면 이동 창. 메뉴 이름이나 그룹 이름으로 찾는다. */
export function CommandPalette({ isOpen, isAdmin, onClose }: CommandPaletteProps) {
  const navigate = useNavigate()
  const listId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)

  const entries = useMemo(() => buildEntries(isAdmin), [isAdmin])
  const normalized = query.trim().toLowerCase()
  const matches = normalized
    ? entries.filter(({ item, group }) => `${item.label} ${group}`.toLowerCase().includes(normalized))
    : entries
  const activeIndex = Math.min(cursor, Math.max(matches.length - 1, 0))

  useEffect(() => {
    if (!isOpen) return
    setQuery('')
    setCursor(0)
    inputRef.current?.focus()
  }, [isOpen])

  if (!isOpen) return null

  const go = (entry: PaletteEntry | undefined) => {
    if (!entry) return
    onClose()
    navigate(entry.item.to)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((activeIndex + 1) % Math.max(matches.length, 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((activeIndex - 1 + matches.length) % Math.max(matches.length, 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      go(matches[activeIndex])
    }
  }

  return createPortal(
    <div
      className="ds-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="ds-command" role="dialog" aria-modal="true" aria-label="화면 찾기">
        <input
          ref={inputRef}
          className="ds-command__input"
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={matches.length > 0 ? `${listId}-${activeIndex}` : undefined}
          aria-label="이동할 화면 이름"
          placeholder="이동할 화면 이름을 입력하세요"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setCursor(0)
          }}
          onKeyDown={handleKeyDown}
        />
        <ul className="ds-command__list" id={listId} role="listbox" aria-label="화면 목록">
          {matches.length === 0 && <li className="ds-command__group">맞는 화면이 없습니다.</li>}
          {matches.map((entry, index) => {
            const Icon = entry.item.icon
            const showGroup = index === 0 || matches[index - 1].group !== entry.group
            return (
              <li key={entry.item.to} role="presentation">
                {showGroup && <div className="ds-command__group" aria-hidden="true">{entry.group}</div>}
                <div
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === activeIndex}
                  className="ds-command__item"
                  onMouseEnter={() => setCursor(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => go(entry)}
                >
                  <Icon size={16} aria-hidden="true" />
                  {entry.item.label}
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </div>,
    document.body,
  )
}
