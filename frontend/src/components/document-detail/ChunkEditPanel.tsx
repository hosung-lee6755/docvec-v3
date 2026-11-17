import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import type { DocumentChunk2 as DocumentChunk, useMergeChunk, useUpdateChunk } from '../../hooks/useDocuments'
import { ErrorText } from '../ui'

type EditMode = 'text' | 'prev' | 'next'

interface ChunkEditPanelProps {
  documentId: string
  chunk: DocumentChunk
  prevChunk: DocumentChunk | null
  nextChunk: DocumentChunk | null
  text: string
  updateChunk: ReturnType<typeof useUpdateChunk>
  mergeChunk: ReturnType<typeof useMergeChunk>
  onTextChange: (text: string) => void
  onClose: () => void
}

const MODES: { value: EditMode; label: string }[] = [
  { value: 'text', label: '글 수정' },
  { value: 'prev', label: '앞 청크에 합치기' },
  { value: 'next', label: '뒤 청크에 합치기' },
]

// 합친 결과는 이어 붙는 자리를 보여 준다. 상대 청크는 맞닿는 쪽 끝부분만 줄여 보인다
const CONTEXT_CHARS = 120

function tail(text: string) {
  return text.length > CONTEXT_CHARS ? `…${text.slice(-CONTEXT_CHARS)}` : text
}

function head(text: string) {
  return text.length > CONTEXT_CHARS ? `${text.slice(0, CONTEXT_CHARS)}…` : text
}

/** 청크 수정 창. 글을 고치거나, 이 청크를 앞뒤 청크에 붙여 하나로 만든다. */
export default function ChunkEditPanel({
  documentId, chunk, prevChunk, nextChunk, text, updateChunk, mergeChunk, onTextChange, onClose,
}: ChunkEditPanelProps) {
  const [mode, setMode] = useState<EditMode>('text')
  const target = mode === 'prev' ? prevChunk : mode === 'next' ? nextChunk : null
  const isBusy = updateChunk.isPending || mergeChunk.isPending
  const saveLabel = chunk.embedded ? '저장 (재임베딩)' : '저장'

  const mergedLength = target ? target.text.length + 1 + chunk.text.length : 0
  const joinPreview = target
    ? (mode === 'prev' ? `${tail(target.text)}\n${chunk.text}` : `${chunk.text}\n${head(target.text)}`)
    : ''

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div role="radiogroup" aria-label="수정 방식" style={{ display: 'flex', gap: 4 }}>
        {MODES.map(({ value, label }) => {
          const isUnavailable = (value === 'prev' && !prevChunk) || (value === 'next' && !nextChunk)
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={mode === value}
              disabled={isUnavailable || isBusy}
              title={isUnavailable ? `${value === 'prev' ? '앞' : '뒤'}에 합칠 청크가 없습니다` : undefined}
              onClick={() => setMode(value)}
              className={`ds-btn ds-btn--sm ${mode === value ? 'ds-btn--primary' : 'ds-btn--secondary'}`}
            >
              {label}
            </button>
          )
        })}
      </div>

      {mode === 'text' && (
        <textarea
          className="ds-input"
          aria-label="청크 글"
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          rows={8}
          style={{ width: '100%', boxSizing: 'border-box', fontSize: 12, lineHeight: 1.6, fontFamily: 'inherit', resize: 'vertical' }}
        />
      )}

      {target && (
        <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <p style={{ margin: 0, color: 'var(--color-text-muted)' }}>
            이 청크를 청크 #{target.chunk_index + 1}의 {mode === 'prev' ? '끝에' : '앞에'} 붙이고 이 청크는 지웁니다.
            {chunk.embedded ? ' 합친 청크는 다시 임베딩됩니다.' : ' 검토를 승인하면 합친 글로 임베딩됩니다.'}
          </p>
          <pre
            aria-label="합친 결과 미리보기"
            style={{
              margin: 0, padding: 'var(--space-2)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'inherit',
              background: 'var(--color-surface-subtle)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)',
            }}
          >
            {joinPreview}
            <span style={{ display: 'block', marginTop: 4, color: 'var(--color-text-muted)' }}>합친 뒤 {mergedLength}자</span>
          </pre>
        </div>
      )}

      {updateChunk.isError && <ErrorText error={updateChunk.error} message="청크를 저장하지 못했습니다." />}
      {mergeChunk.isError && <ErrorText error={mergeChunk.error} message="청크를 합치지 못했습니다." />}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
        <button type="button" onClick={onClose} disabled={isBusy} className="ds-btn ds-btn--secondary ds-btn--sm">
          취소
        </button>
        {mode === 'text' ? (
          <button
            type="button"
            onClick={() => updateChunk.mutate({ docId: documentId, chunkId: chunk.id, text }, { onSuccess: onClose })}
            disabled={isBusy || !text.trim()}
            className="ds-btn ds-btn--primary ds-btn--sm"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            {updateChunk.isPending && <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />}
            {saveLabel}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => mergeChunk.mutate({ docId: documentId, chunkId: chunk.id, direction: mode }, { onSuccess: onClose })}
            disabled={isBusy || !target}
            className="ds-btn ds-btn--primary ds-btn--sm"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            {mergeChunk.isPending && <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />}
            합치기
          </button>
        )}
      </div>
    </div>
  )
}
