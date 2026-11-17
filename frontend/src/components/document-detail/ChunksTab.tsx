import { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { chunkWarningKind, type ChunkWarningKind } from '../../lib/qualityTargets'
import ChunkWarningBar from './ChunkWarningBar'
import ChunkEditPanel from './ChunkEditPanel'
import type { DocumentChunksResult, useDeleteChunk, useMergeChunk, useUpdateChunk } from '../../hooks/useDocuments'
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
  // 품질 보고서가 짚은 청크 id → 경고 종류. 보고서가 없으면 null이고 글자 수로 판단한다
  warningKinds: Map<string, ChunkWarningKind> | null
  updateChunk: ReturnType<typeof useUpdateChunk>
  deleteChunk: ReturnType<typeof useDeleteChunk>
  mergeChunk: ReturnType<typeof useMergeChunk>
  // 품질 게이트에서 멈춘 문서. 청크가 아직 임베딩 전이라도 고치고 지우고 합칠 수 있다
  isReviewDraft: boolean
  // 원문 대조에 갔다가 돌아왔을 때 다시 보여 줄 청크
  focusChunkId: string | null
  onChunkEditIdChange: (id: string | null) => void
  onChunkEditTextChange: (text: string) => void
  onExpandedParentChunkIdChange: (id: string | null) => void
  onViewInOriginal: (page: number, chunkId: string) => void
}

// Parent Retrieval의 뜻. 검색은 작은 청크로 정확하게 찾고, 답변을 만들 때만 같은 상위 절의 앞뒤 청크를 함께 넘긴다.
const PARENT_RETRIEVAL_HINT =
  '상위 청크는 이 청크가 속한 상위 절의 연속 청크를 묶은 것입니다. 검색은 이 청크로 하고, 채팅 답변을 만들 때 ' +
  '같은 상위 절의 앞뒤 청크(검색 제외된 청크는 빼고, 근거마다 약 1,200자 안)를 함께 넘겨 문맥을 보완합니다. ' +
  '컬렉션 검색 설정에서 끌 수 있습니다.'

function scrollToChunk(id: string) {
  requestAnimationFrame(() => {
    document.getElementById(`chunk-row-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
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
  warningKinds,
  updateChunk,
  deleteChunk,
  mergeChunk,
  isReviewDraft,
  focusChunkId,
  onChunkEditIdChange,
  onChunkEditTextChange,
  onExpandedParentChunkIdChange,
  onViewInOriginal,
}: ChunksTabProps) {
  const [onlyFlagged, setOnlyFlagged] = useState(false)
  const [pickedId, setPickedId] = useState<string | null>(focusChunkId)
  const scrolledForRef = useRef<string[] | null>(null)
  const chunks = chunksResult?.chunks
  const flagged = (chunks ?? []).filter((chunk) => chunkWarningKind(chunk, warningKinds))
  // 품질 탭이나 검토 안내에서 경고를 눌러 들어오면 그 경고의 첫 대상을 가리킨다
  // 보고서의 id 순서가 아니라 문서 순서로 첫 대상을 고른다
  const requestedId = (highlightChunkIds && chunks?.find((chunk) => highlightChunkIds.includes(chunk.id))?.id) ?? null
  const activeId = pickedId ?? requestedId

  // 같은 요청으로 두 번 스크롤하지 않는다(청크 목록을 다시 받아와도 화면이 튀지 않게)
  useEffect(() => {
    if (!requestedId || !highlightChunkIds || scrolledForRef.current === highlightChunkIds) return
    scrolledForRef.current = highlightChunkIds
    scrollToChunk(requestedId)
  }, [requestedId, highlightChunkIds])

  // 원문 대조에서 돌아오면 보던 청크로 다시 스크롤한다
  const isFocusLoaded = !!focusChunkId && !!chunks?.some((chunk) => chunk.id === focusChunkId)
  useEffect(() => {
    if (isFocusLoaded && focusChunkId) scrollToChunk(focusChunkId)
  }, [isFocusLoaded, focusChunkId])

  const handleJump = (index: number) => {
    const target = flagged[index]
    if (!target) return
    setPickedId(target.id)
    scrollToChunk(target.id)
  }

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

  const visibleChunks = onlyFlagged && flagged.length ? flagged : chunksResult.chunks

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <ChunkWarningBar
        shortCount={flagged.filter((chunk) => chunkWarningKind(chunk, warningKinds) === 'short').length}
        longCount={flagged.filter((chunk) => chunkWarningKind(chunk, warningKinds) === 'long').length}
        currentIndex={flagged.findIndex((chunk) => chunk.id === activeId)}
        onlyFlagged={onlyFlagged}
        onJump={handleJump}
        onOnlyFlaggedChange={setOnlyFlagged}
      />
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
          {isReviewDraft
            ? '아직 임베딩 전입니다. 검토를 승인하기 전에 청크 글을 고치거나, 지우거나, 짧은 청크를 앞뒤 청크와 합칠 수 있고, '
              + '고친 내용은 승인 후 임베딩에 그대로 반영됩니다. 검색 제외는 승인 뒤에 할 수 있습니다. '
            : '아직 임베딩되지 않은 미리보기입니다. 이 상태에서는 고칠 수 없습니다. '}
          표시된 청크는 너무 짧거나(50자 미만) 너무 깁니다(2000자 초과).
        </p>
      )}
      {visibleChunks.map((chunk) => {
        const order = chunksResult.chunks.findIndex((c) => c.id === chunk.id)
        const prevChunk = order > 0 ? chunksResult.chunks[order - 1] : null
        const nextChunk = order >= 0 ? chunksResult.chunks[order + 1] ?? null : null
        const canEdit = chunk.embedded || isReviewDraft
        const warningKind = chunkWarningKind(chunk, warningKinds)
        const isTooShort = warningKind === 'short'
        const isTooLong = warningKind === 'long'
        const isJumpTarget = chunk.id === activeId
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
            {/* 메타 정보는 줄바꿈되고, 오른쪽 버튼 묶음은 한 줄로 고정한다(2026-11-13) */}
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 'var(--space-2)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', flex: 1, minWidth: 0 }}>
              <span style={{ fontSize: 12, fontWeight: 600 }}>
                청크 #{chunk.chunk_index + 1}
                {isPdfDoc && chunk.page_number ? ` · ${chunk.page_number}쪽` : ''}
              </span>
              <span style={{ fontSize: 11, color: (isTooShort || isTooLong) ? 'var(--color-warning)' : 'var(--color-text-muted)' }}>
                {chunk.text.length}자{isTooShort ? ' · 너무 짧음' : isTooLong ? ' · 너무 김' : ''}
              </span>
              {warningKind && <span className="ds-badge ds-badge--warning">품질 경고 대상</span>}
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
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, whiteSpace: 'nowrap' }}>
              {chunk.page_number != null && (
                <button
                  onClick={() => onViewInOriginal(chunk.page_number as number, chunk.id)}
                  className="ds-btn ds-btn--ghost ds-btn--sm"
                  style={{ cursor: 'pointer' }}
                >
                  원문 대조에서 보기
                </button>
              )}
              {canEdit && chunkEditId !== chunk.id && (
                <>
                  <button
                    onClick={() => { onChunkEditIdChange(chunk.id); onChunkEditTextChange(chunk.text) }}
                    className="ds-btn ds-btn--ghost ds-btn--sm"
                    style={{ cursor: 'pointer' }}
                  >
                    수정
                  </button>
                  {chunk.embedded && <button
                    onClick={() => updateChunk.mutate({ docId: documentId, chunkId: chunk.id, disabled: !chunk.disabled })}
                    disabled={updateChunk.isPending}
                    className="ds-btn ds-btn--ghost ds-btn--sm"
                    style={{ cursor: 'pointer' }}
                  >
                    {chunk.disabled ? '검색 포함' : '검색 제외'}
                  </button>}
                  <button
                    onClick={() => {
                      const where = chunk.embedded ? '벡터DB에서 제거되며 ' : ''
                      if (window.confirm(`청크 #${chunk.chunk_index + 1}을(를) 삭제하시겠습니까? ${where}되돌릴 수 없습니다.`)) {
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
                  title={PARENT_RETRIEVAL_HINT}
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
                {expandedParentChunkId === chunk.id && (
                  <p style={{ fontSize: 11, color: 'var(--color-text-muted)', margin: '4px 0 0' }}>{PARENT_RETRIEVAL_HINT}</p>
                )}
              </div>
            )}
            {chunkEditId === chunk.id ? (
              <ChunkEditPanel
                documentId={documentId}
                chunk={chunk}
                prevChunk={prevChunk}
                nextChunk={nextChunk}
                text={chunkEditText}
                updateChunk={updateChunk}
                mergeChunk={mergeChunk}
                onTextChange={onChunkEditTextChange}
                onClose={() => onChunkEditIdChange(null)}
              />
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
