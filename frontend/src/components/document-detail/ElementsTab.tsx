import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import {
  useDocumentElements, useUpdateDocumentElement, type DocumentElementItem,
} from '../../hooks/useDocumentElements'

const TYPE_LABELS: Record<string, string> = {
  title: '제목', section_header: '제목', table: '표', list_item: '목록 항목',
  picture: '그림', figure: '그림', caption: '캡션', footnote: '각주',
  page_header: '머리말', page_footer: '꼬리말', document_index: '목차', text: '문단',
}

export default function ElementsTab({ documentId }: { documentId: string }) {
  const { data, isLoading, isError } = useDocumentElements(documentId)
  const updateElement = useUpdateDocumentElement()
  const [editId, setEditId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  // 메타 정보 생성.txt 2절 — Docling이 폰트 정보를 노출하지 않아 항상 비어
  // 있는 style/font_size/font_name을 사용자가 직접 입력하는 필드(9항목
  // 펀치리스트 후속, 2026-07-24).
  const [editStyle, setEditStyle] = useState('')
  const [editFontSize, setEditFontSize] = useState('')
  const [editFontName, setEditFontName] = useState('')

  const elements = data?.elements ?? []

  const handleStartEdit = (el: DocumentElementItem) => {
    setEditId(el.id)
    setEditText(el.content.markdown ?? el.content.text ?? '')
    setEditStyle(el.metadata.style ?? '')
    setEditFontSize(el.metadata.font_size != null ? String(el.metadata.font_size) : '')
    setEditFontName(el.metadata.font_name ?? '')
  }

  const handleSave = (elementId: string) => {
    updateElement.mutate(
      {
        documentId, elementId, markdown: editText,
        style: editStyle || undefined,
        fontSize: editFontSize ? Number(editFontSize) : undefined,
        fontName: editFontName || undefined,
      },
      { onSuccess: () => setEditId(null) },
    )
  }

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  if (isError) {
    return <p style={{ color: 'var(--color-danger)', fontSize: 13, margin: 0 }}>요소를 불러오는 중 오류가 발생했습니다.</p>
  }

  if (!elements.length) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
        표시할 요소가 없습니다 — 이 문서는 Docling 엔진으로 처리되지 않았습니다(레거시 엔진 문서는
        표/구조 탭에서 확인해주세요).
      </p>
    )
  }

  const correctedCount = elements.filter((el) => el.user_corrected).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
        요소 {elements.length}개 · 사용자 보정 {correctedCount}개 — markdown을 수정하면 이 요소의 내용만 바뀌며,
        구조/청크에 반영하려면 재처리가 필요합니다.
      </p>
      {elements.map((el) => {
        const isEditing = editId === el.id
        const displayText = el.content.markdown ?? el.content.text ?? ''
        return (
          <div
            key={el.id}
            style={{
              border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)',
              padding: 'var(--space-3)', background: 'var(--color-surface)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--space-2)' }}>
              <span className="ds-badge ds-badge--info">{TYPE_LABELS[el.type] ?? el.type}</span>
              {el.page != null && <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{el.page}쪽</span>}
              {el.metadata.order != null && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>순서 {el.metadata.order}</span>
              )}
              {!!el.metadata.section_path?.length && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  {el.metadata.section_path.join(' > ')}
                </span>
              )}
              {el.metadata.is_header && <span className="ds-badge ds-badge--neutral">머리말</span>}
              {el.metadata.is_footer && <span className="ds-badge ds-badge--neutral">꼬리말</span>}
              {el.metadata.is_caption && <span className="ds-badge ds-badge--neutral">캡션</span>}
              {el.type === 'table' && el.metadata.table_rows != null && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  {el.metadata.table_rows}행 × {el.metadata.table_cols}열
                </span>
              )}
              {el.metadata.image_path && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }} title={el.metadata.image_path}>
                  🖼 {el.metadata.image_path.split('/').pop()}
                </span>
              )}
              {(el.metadata.style || el.metadata.font_size || el.metadata.font_name) && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  {[el.metadata.style, el.metadata.font_name, el.metadata.font_size && `${el.metadata.font_size}pt`]
                    .filter(Boolean).join(' · ')}
                </span>
              )}
              {el.user_corrected && <span className="ds-badge ds-badge--info">수정됨</span>}
              <span style={{ flex: 1 }} />
              {!isEditing && (
                <button
                  onClick={() => handleStartEdit(el)}
                  className="ds-btn ds-btn--ghost ds-btn--sm"
                  style={{ cursor: 'pointer' }}
                >
                  수정
                </button>
              )}
            </div>
            {isEditing ? (
              <div>
                <textarea
                  className="ds-input"
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  rows={8}
                  style={{ width: '100%', boxSizing: 'border-box', fontSize: 12, lineHeight: 1.6, fontFamily: 'inherit', resize: 'vertical' }}
                />
                <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 11, color: 'var(--color-text-muted)' }}>
                  <label>
                    스타일{' '}
                    <input
                      value={editStyle}
                      onChange={(e) => setEditStyle(e.target.value)}
                      placeholder="예: Heading1"
                      style={{ fontSize: 11, border: '1px solid var(--color-border)', borderRadius: 4, padding: '2px 6px', width: 90 }}
                    />
                  </label>
                  <label>
                    글자 크기{' '}
                    <input
                      type="number"
                      value={editFontSize}
                      onChange={(e) => setEditFontSize(e.target.value)}
                      placeholder="pt"
                      style={{ fontSize: 11, border: '1px solid var(--color-border)', borderRadius: 4, padding: '2px 6px', width: 60 }}
                    />
                  </label>
                  <label>
                    글꼴{' '}
                    <input
                      value={editFontName}
                      onChange={(e) => setEditFontName(e.target.value)}
                      placeholder="예: 맑은 고딕"
                      style={{ fontSize: 11, border: '1px solid var(--color-border)', borderRadius: 4, padding: '2px 6px', width: 100 }}
                    />
                  </label>
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
                  <button
                    onClick={() => setEditId(null)}
                    disabled={updateElement.isPending}
                    className="ds-btn ds-btn--secondary ds-btn--sm"
                    style={{ cursor: 'pointer' }}
                  >
                    취소
                  </button>
                  <button
                    onClick={() => handleSave(el.id)}
                    disabled={updateElement.isPending || !editText.trim()}
                    className="ds-btn ds-btn--primary ds-btn--sm"
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}
                  >
                    {updateElement.isPending && <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />}
                    저장
                  </button>
                </div>
              </div>
            ) : (
              <pre style={{
                fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                fontFamily: 'inherit', margin: 0, color: 'var(--color-text)',
              }}>
                {displayText || <span style={{ color: 'var(--color-text-muted)' }}>(내용 없음)</span>}
              </pre>
            )}
          </div>
        )
      })}
    </div>
  )
}
