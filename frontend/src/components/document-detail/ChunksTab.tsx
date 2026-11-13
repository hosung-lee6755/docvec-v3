import { Loader2 } from 'lucide-react'
import type { TabKey } from './documentDetailHelpers'
import type { DocumentChunksResult, useDeleteChunk, useUpdateChunk } from '../../hooks/useDocuments'
import { ErrorText } from '../ui'

interface ChunksTabProps {
  documentId: string
  isLoading: boolean
  isError: boolean
  error?: unknown
  chunksResult: DocumentChunksResult | undefined
  isPdfDoc: boolean
  chunkEditId: string | null
  chunkEditText: string
  expandedParentChunkId: string | null
  highlightChunkIds: string[] | null
  updateChunk: ReturnType<typeof useUpdateChunk>
  deleteChunk: ReturnType<typeof useDeleteChunk>
  onChunkEditIdChange: (id: string | null) => void
  onChunkEditTextChange: (text: string) => void
  onExpandedParentChunkIdChange: (id: string | null) => void
  onOriginalPageChange: (page: number) => void
  onActivateTab: (tab: TabKey) => void
}

export default function ChunksTab({
  documentId,
  isLoading,
  isError,
  error,
  chunksResult,
  isPdfDoc,
  chunkEditId,
  chunkEditText,
  expandedParentChunkId,
  highlightChunkIds,
  updateChunk,
  deleteChunk,
  onChunkEditIdChange,
  onChunkEditTextChange,
  onExpandedParentChunkIdChange,
  onOriginalPageChange,
  onActivateTab,
}: ChunksTabProps) {
  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorText error={error} message="청크를 불러오지 못했습니다." />
    )
  }

  if (!chunksResult?.chunks.length) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
        저장된 청크가 없습니다.
      </p>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
        총 {chunksResult.chunks.length}개 청크
        {(() => {
          const tokenCounts = chunksResult.chunks.map((c) => c.token_count).filter((t): t is number => t != null)
          if (!tokenCounts.length) return null
          const avg = Math.round(tokenCounts.reduce((a, b) => a + b, 0) / tokenCounts.length)
          return ` · 평균 ${avg}토큰`
        })()}
        . 텍스트를 수정하면 해당 청크만 다시 임베딩되고,
        "검색 제외"된 청크는 검색·채팅에서 사용되지 않습니다.
      </p>
      {chunksResult.chunks.some((c) => !c.embedded) && (
        <p style={{ fontSize: 12, color: 'var(--color-warning)', margin: 0 }}>
          아직 임베딩되지 않은 미리보기입니다(검토 승인 후 벡터 저장이 진행됩니다). 이 상태에서는
          수정·검색 제외·삭제를 할 수 없고, 품질 경고에서 언급된 청크 길이를 확인하는 용도로만 쓸 수 있습니다.
          아래 굵게 표시된 청크는 너무 짧거나(50자 미만) 너무 깁니다(2000자 초과).
        </p>
      )}
      {chunksResult.chunks.map((chunk) => {
        const isTooShort = chunk.text.length < 50
        const isTooLong = chunk.text.length > 2000
        const isJumpTarget = !!highlightChunkIds?.includes(chunk.id)
        return (
          <div
            key={chunk.id}
            id={`chunk-row-${chunk.id}`}
            style={{
              border: isJumpTarget ? '2px solid var(--color-accent)'
                : (isTooShort || isTooLong) ? '1px solid var(--color-warning-border)' : '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--space-3)', background: (isTooShort || isTooLong) ? 'var(--color-warning-bg)' : 'var(--color-surface)',
              opacity: chunk.disabled ? 0.55 : 1,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--space-2)', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12, fontWeight: 600 }}>
                청크 #{chunk.chunk_index + 1}
                {isPdfDoc && chunk.page_number ? ` · ${chunk.page_number}쪽` : ''}
              </span>
              <span style={{ fontSize: 11, color: (isTooShort || isTooLong) ? 'var(--color-warning)' : 'var(--color-text-muted)' }}>
                {chunk.text.length}자{isTooShort ? ' · 너무 짧음' : isTooLong ? ' · 너무 김' : ''}
              </span>
              {!chunk.embedded && <span className="ds-badge ds-badge--warning">임베딩 전 미리보기</span>}
              {chunk.edited && <span className="ds-badge ds-badge--info">수정됨</span>}
              {chunk.disabled && <span className="ds-badge ds-badge--neutral">검색 제외</span>}
              {chunk.chunk_type && <span className="ds-badge ds-badge--neutral">{chunk.chunk_type}</span>}
              {chunk.token_count != null && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  토큰 ~{chunk.token_count}
                </span>
              )}
              {!!chunk.section_path?.length && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }} title="섹션 경로">
                  {chunk.section_path.join(' > ')}
                </span>
              )}
              {!!chunk.keywords?.length && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  #{chunk.keywords.join(' #')}
                </span>
              )}
              {chunk.embedding_model && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }} title="임베딩 모델">
                  {chunk.embedding_model}
                  {chunk.version ? ` (v${chunk.version})` : ''}
                </span>
              )}
              {chunk.language && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }} title="언어">
                  {chunk.language}
                </span>
              )}
              {chunk.source_file && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }} title="원본 파일명">
                  📄 {chunk.source_file}
                </span>
              )}
              {chunk.embedded && (
                <span
                  title="검색/채팅 응답에서 이 청크가 실제로 반환된 횟수"
                  style={{
                    fontSize: 11,
                    color: chunk.hit_count > 0 ? 'var(--color-text-muted)' : 'var(--color-warning)',
                  }}
                >
                  조회 {chunk.hit_count}회{chunk.hit_count === 0 ? ' · 미조회' : ''}
                </span>
              )}
              <span style={{ flex: 1 }} />
              {chunk.page_number != null && (
                <button
                  onClick={() => { onOriginalPageChange(chunk.page_number as number); onActivateTab('original') }}
                  className="ds-btn ds-btn--ghost ds-btn--sm"
                  style={{ cursor: 'pointer' }}
                >
                  원문 대조에서 보기
                </button>
              )}
              {chunk.embedded && chunkEditId !== chunk.id && (
                <>
                  <button
                    onClick={() => { onChunkEditIdChange(chunk.id); onChunkEditTextChange(chunk.text) }}
                    className="ds-btn ds-btn--ghost ds-btn--sm"
                    style={{ cursor: 'pointer' }}
                  >
                    수정
                  </button>
                  <button
                    onClick={() => updateChunk.mutate({ docId: documentId, chunkId: chunk.id, disabled: !chunk.disabled })}
                    disabled={updateChunk.isPending}
                    className="ds-btn ds-btn--ghost ds-btn--sm"
                    style={{ cursor: 'pointer' }}
                  >
                    {chunk.disabled ? '검색 포함' : '검색 제외'}
                  </button>
                  <button
                    onClick={() => {
                      if (window.confirm(`청크 #${chunk.chunk_index + 1}을(를) 삭제하시겠습니까? 벡터DB에서 제거되며 되돌릴 수 없습니다.`)) {
                        deleteChunk.mutate({ docId: documentId, chunkId: chunk.id })
                      }
                    }}
                    disabled={deleteChunk.isPending}
                    className="ds-btn ds-btn--ghost ds-btn--sm"
                    style={{ cursor: 'pointer', color: 'var(--color-danger)' }}
                  >
                    삭제
                  </button>
                </>
              )}
            </div>
            {(chunk.prev_chunk_id || chunk.next_chunk_id) && (
              <div style={{ display: 'flex', gap: 12, fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 'var(--space-2)' }}>
                {chunk.prev_chunk_id && (
                  <button
                    onClick={() => document.getElementById(`chunk-row-${chunk.prev_chunk_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                    className="ds-btn ds-btn--ghost ds-btn--sm"
                    style={{ cursor: 'pointer', fontSize: 11, padding: 0 }}
                  >
                    ◀ 이전 청크
                  </button>
                )}
                {chunk.next_chunk_id && (
                  <button
                    onClick={() => document.getElementById(`chunk-row-${chunk.next_chunk_id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                    className="ds-btn ds-btn--ghost ds-btn--sm"
                    style={{ cursor: 'pointer', fontSize: 11, padding: 0 }}
                  >
                    다음 청크 ▶
                  </button>
                )}
              </div>
            )}
            {chunk.parent_chunk_text && (
              <div style={{ marginBottom: 'var(--space-2)' }}>
                <button
                  onClick={() => onExpandedParentChunkIdChange(expandedParentChunkId === chunk.id ? null : chunk.id)}
                  className="ds-btn ds-btn--ghost ds-btn--sm"
                  style={{ cursor: 'pointer', fontSize: 11, padding: 0, color: 'var(--color-text-muted)' }}
                >
                  {expandedParentChunkId === chunk.id ? '▾' : '▸'} 상위 청크 보기 (Parent Retrieval)
                </button>
                {expandedParentChunkId === chunk.id && (
                  <pre style={{
                    fontSize: 11, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    fontFamily: 'inherit', margin: '6px 0 0', padding: 'var(--space-2)',
                    background: 'var(--color-surface-subtle)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)',
                    color: 'var(--color-text-secondary)',
                  }}>
                    {chunk.parent_chunk_text}
                  </pre>
                )}
              </div>
            )}
            {chunkEditId === chunk.id ? (
              <div>
                <textarea
                  className="ds-input"
                  value={chunkEditText}
                  onChange={(e) => onChunkEditTextChange(e.target.value)}
                  rows={8}
                  style={{ width: '100%', boxSizing: 'border-box', fontSize: 12, lineHeight: 1.6, fontFamily: 'inherit', resize: 'vertical' }}
                />
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
                  <button
                    onClick={() => onChunkEditIdChange(null)}
                    disabled={updateChunk.isPending}
                    className="ds-btn ds-btn--secondary ds-btn--sm"
                    style={{ cursor: 'pointer' }}
                  >
                    취소
                  </button>
                  <button
                    onClick={() =>
                      updateChunk.mutate(
                        { docId: documentId, chunkId: chunk.id, text: chunkEditText },
                        { onSuccess: () => onChunkEditIdChange(null) }
                      )
                    }
                    disabled={updateChunk.isPending || !chunkEditText.trim()}
                    className="ds-btn ds-btn--primary ds-btn--sm"
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}
                  >
                    {updateChunk.isPending && <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />}
                    저장 (재임베딩)
                  </button>
                </div>
              </div>
            ) : (
              <pre style={{
                fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                fontFamily: 'inherit', margin: 0, color: 'var(--color-text)',
              }}>
                {chunk.text}
              </pre>
            )}
          </div>
        )
      })}
    </div>
  )
}
