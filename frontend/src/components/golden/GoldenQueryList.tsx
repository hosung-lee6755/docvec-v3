import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import type { GoldenQuery } from '../../hooks/useGoldenQueries'

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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 260, overflowY: 'auto' }}>
      {items.map((gq) =>
        editingId === gq.id ? (
          <div key={gq.id} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', fontSize: 12, padding: 'var(--space-2)', background: '#f8fafc', borderRadius: 'var(--radius-sm)' }}>
            <input
              type="text"
              aria-label="질문 수정"
              value={draftQuery}
              onChange={(e) => setDraftQuery(e.target.value)}
              className="krds-input"
              style={{ width: '100%' }}
            />
            <div style={{ maxHeight: 120, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
              {optionsFor(gq).map((d) => (
                <label key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <input type="checkbox" checked={draftExpected.has(d.id)} onChange={() => toggleDraftExpected(d.id)} />
                  {d.name}
                </label>
              ))}
            </div>
            {!canSave && <span style={{ color: '#b45309' }}>질문과 기대 문서를 하나 이상 입력하세요.</span>}
            <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
              <button type="button" onClick={() => handleSave(gq.id)} disabled={isSaving || !canSave} className="krds-btn xsmall primary">
                저장
              </button>
              <button type="button" onClick={() => setEditingId(null)} className="krds-btn xsmall secondary">
                취소
              </button>
            </div>
          </div>
        ) : (
          <div key={gq.id} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-2)',
            fontSize: 12, padding: 'var(--space-1) var(--space-2)', background: '#f8fafc', borderRadius: 'var(--radius-sm)',
          }}>
            <span>
              {gq.query} <span style={{ color: 'var(--color-text-muted)' }}>({gq.expected_document_ids.length}개 문서)</span>
            </span>
            <span style={{ display: 'flex', gap: 'var(--space-1)' }}>
              <button type="button" onClick={() => startEdit(gq)} className="krds-btn text xsmall">수정</button>
              <button type="button" onClick={() => onDelete(gq.id)} className="krds-btn text xsmall" aria-label="골든 쿼리 삭제">
                <Trash2 size={12} />
              </button>
            </span>
          </div>
        ),
      )}
      {saveError && <p role="alert" style={{ color: '#dc2626', fontSize: 12, margin: 0 }}>{saveError}</p>}
    </div>
  )
}
