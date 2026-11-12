import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import type { GoldenQuery } from '../../hooks/useGoldenQueries'
import { Alert, Button, IconButton, Input } from '../ui'

export interface GoldenDocOption {
  id: string
  name: string
}

interface GoldenQueryListProps {
  items: GoldenQuery[]
  docOptions: GoldenDocOption[]
  isSaving: boolean
  saveError: string | null
  onSave: (queryId: string, input: { query: string; expected_document_ids: string[] }) => void
  onDelete: (queryId: string) => void
}

export default function GoldenQueryList({ items, docOptions, isSaving, saveError, onSave, onDelete }: GoldenQueryListProps) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftQuery, setDraftQuery] = useState('')
  const [draftExpected, setDraftExpected] = useState<Set<string>>(new Set())

  const startEdit = (gq: GoldenQuery) => {
    setEditingId(gq.id)
    setDraftQuery(gq.query)
    setDraftExpected(new Set(gq.expected_document_ids))
  }

  const toggleDraftExpected = (docId: string) =>
    setDraftExpected((prev) => {
      const next = new Set(prev)
      next.has(docId) ? next.delete(docId) : next.add(docId)
      return next
    })

  const canSave = !!draftQuery.trim() && draftExpected.size > 0

  const handleSave = (queryId: string) => {
    if (!canSave) return
    onSave(queryId, { query: draftQuery.trim(), expected_document_ids: Array.from(draftExpected) })
    setEditingId(null)
  }

  // 기대 문서 목록에는 현재 컬렉션의 문서 외에, 이 질문이 이미 가리키는 문서(예: 이전 버전)도 넣어 둔다.
  const optionsFor = (gq: GoldenQuery): GoldenDocOption[] => {
    const known = new Set(docOptions.map((d) => d.id))
    const extra = gq.expected_document_ids
      .filter((id) => !known.has(id))
      .map((id) => ({ id, name: `${id.slice(0, 8)} (목록에 없는 문서)` }))
    return [...docOptions, ...extra]
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)', maxHeight: 260, overflowY: 'auto' }}>
      {items.map((gq) =>
        editingId === gq.id ? (
          <div
            key={gq.id}
            style={{
              display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', fontSize: 'var(--text-sm)',
              padding: 'var(--space-3)', background: 'var(--color-surface-subtle)', borderRadius: 'var(--radius-md)',
            }}
          >
            <Input
              type="text"
              aria-label="질문 수정"
              value={draftQuery}
              onChange={(e) => setDraftQuery(e.target.value)}
              controlSize="sm"
            />
            <div style={{ maxHeight: 120, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
              {optionsFor(gq).map((d) => (
                <label key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                  <input type="checkbox" checked={draftExpected.has(d.id)} onChange={() => toggleDraftExpected(d.id)} />
                  {d.name}
                </label>
              ))}
            </div>
            {!canSave && <Alert tone="warning">질문과 기대 문서를 하나 이상 입력하세요.</Alert>}
            <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
              <Button size="sm" variant="primary" onClick={() => handleSave(gq.id)} disabled={isSaving || !canSave}>
                저장
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setEditingId(null)}>
                취소
              </Button>
            </div>
          </div>
        ) : (
          <div
            key={gq.id}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-2)',
              fontSize: 'var(--text-sm)', padding: 'var(--space-2) var(--space-3)',
              background: 'var(--color-surface-subtle)', borderRadius: 'var(--radius-md)',
            }}
          >
            <span>
              {gq.query}{' '}
              <span style={{ color: 'var(--color-text-muted)' }}>({gq.expected_document_ids.length}개 문서)</span>
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}>
              <Button size="sm" variant="ghost" onClick={() => startEdit(gq)}>수정</Button>
              <IconButton label="골든 쿼리 삭제" tone="danger" onClick={() => onDelete(gq.id)}>
                <Trash2 size={14} aria-hidden="true" />
              </IconButton>
            </span>
          </div>
        ),
      )}
      {saveError && <Alert tone="danger">{saveError}</Alert>}
    </div>
  )
}
