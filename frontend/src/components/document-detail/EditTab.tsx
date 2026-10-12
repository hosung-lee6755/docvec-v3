import { Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Document, useReprocessDocument, useRestoreRevision } from '../../hooks/useDocuments'
import { ViewModeToggle } from './documentDetailParts'
import { REVISION_SOURCE_LABELS, toBlocksJson, type TabKey } from './documentDetailHelpers'
import type { DocumentNodesResult } from '../../hooks/useDocumentStructure'

interface EditTabProps {
  documentId: string
  doc: Document
  isLoading: boolean
  content: { full_text: string; chunk_count: number } | undefined
  isContentError: boolean
  revisionsResult: { revisions: Array<{ id: string; source: string; created_at: string; text_length: number; preview: string }> } | undefined
  editNodesResult: DocumentNodesResult | undefined
  editedContent: string
  showJson: boolean
  reprocess: ReturnType<typeof useReprocessDocument>
  restoreRevision: ReturnType<typeof useRestoreRevision>
  onEditedContentChange: (text: string) => void
  onShowJsonChange: (v: boolean) => void
  onActivateTab: (tab: TabKey) => void
}

export default function EditTab({
  documentId,
  doc,
  isLoading,
  content,
  isContentError,
  revisionsResult,
  editNodesResult,
  editedContent,
  showJson,
  reprocess,
  restoreRevision,
  onEditedContentChange,
  onShowJsonChange,
  onActivateTab,
}: EditTabProps) {

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  if (isContentError) {
    return (
      <p style={{ color: '#dc2626', fontSize: 13, margin: 0 }}>
        본문을 불러오는 중 오류가 발생했습니다.
      </p>
    )
  }

  if (!content || content.chunk_count === 0) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
        본문을 불러올 수 없습니다.
      </p>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 var(--space-3)', flexShrink: 0 }}>
        불필요한 부분을 제거하거나 수정한 뒤 저장하면, 이 텍스트를 기준으로 청킹·임베딩이 다시 실행되어 기존 검색 결과를 대체하고 요약도 새로 생성됩니다.
      </p>
      <details style={{ flexShrink: 0, marginBottom: 'var(--space-3)', fontSize: 12 }}>
        <summary style={{ cursor: 'pointer', color: 'var(--color-text-muted)', userSelect: 'none' }}>
          문서 메타정보
        </summary>
        <div className="markdown-body" style={{ marginTop: 8, fontSize: 12 }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {[
              `**제목**: ${doc.title || doc.original_filename}`,
              `**언어**: ${doc.language ?? '미판별'}`,
              `**분류**: ${doc.category ?? '미분류'}`,
              `**페이지 수**: ${doc.page_count ?? '-'}`,
              `**작성자**: ${doc.author ?? '미입력'}`,
              `**부서/기관**: ${doc.organization ?? '미입력'}`,
              `**보안 등급**: ${doc.security_level ?? '미입력'}`,
              `**출처 시스템**: ${doc.source_system ?? '미입력'}`,
            ].join('\n\n')}
          </ReactMarkdown>
        </div>
      </details>
      <details style={{ flexShrink: 0, marginBottom: 'var(--space-3)', fontSize: 12 }}>
        <summary style={{ cursor: 'pointer', color: 'var(--color-text-muted)', userSelect: 'none' }}>
          구조 ({editNodesResult?.nodes.length ?? 0}개 노드)
        </summary>
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {editNodesResult && editNodesResult.nodes.length > 0 ? (() => {
            const counts = editNodesResult.nodes.reduce<Record<string, number>>((acc, n) => {
              acc[n.node_type] = (acc[n.node_type] ?? 0) + 1
              return acc
            }, {})
            return (
              <span style={{ color: 'var(--color-text-muted)' }}>
                제목 {(counts.HEADING ?? 0) + (counts.SECTION ?? 0)} · 문단 {counts.PARAGRAPH ?? 0} · 표 {counts.TABLE ?? 0} · 목록 {counts.LIST ?? 0}
              </span>
            )
          })() : (
            <span style={{ color: 'var(--color-text-muted)' }}>구조 분석 결과가 없습니다.</span>
          )}
          <button
            type="button"
            onClick={() => onActivateTab('structure')}
            className="krds-btn text small"
            style={{ cursor: 'pointer', alignSelf: 'flex-start', padding: 0 }}
          >
            구조 탭에서 전체 보기
          </button>
        </div>
      </details>
      <details style={{ flexShrink: 0, marginBottom: 'var(--space-3)', fontSize: 12 }}>
        <summary style={{ cursor: 'pointer', color: 'var(--color-text-muted)', userSelect: 'none' }}>
          변경 이력 ({revisionsResult?.revisions.length ?? 0})
        </summary>
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 200, overflowY: 'auto' }}>
          {(revisionsResult?.revisions ?? []).map((rev, i) => (
            <div key={rev.id} style={{
              display: 'flex', gap: 10, alignItems: 'center',
              border: '1px solid #e2e8f0', borderRadius: 6, padding: '6px 10px',
            }}>
              <span style={{ flexShrink: 0, fontWeight: 600 }}>
                {REVISION_SOURCE_LABELS[rev.source] ?? rev.source}
              </span>
              <span style={{ flexShrink: 0, color: 'var(--color-text-muted)' }}>
                {new Date(rev.created_at).toLocaleString('ko-KR')} · {rev.text_length.toLocaleString()}자
              </span>
              <span style={{
                flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
                whiteSpace: 'nowrap', color: 'var(--color-text-muted)',
              }}>
                {rev.preview}
              </span>
              {i !== 0 && (
                <button
                  onClick={() => {
                    if (window.confirm('이 버전의 텍스트로 되돌리고 다시 청킹·임베딩할까요?')) {
                      restoreRevision.mutate({ docId: documentId, revisionId: rev.id })
                    }
                  }}
                  disabled={restoreRevision.isPending}
                  className="krds-btn secondary small"
                  style={{ flexShrink: 0, cursor: 'pointer' }}
                >
                  복원
                </button>
              )}
            </div>
          ))}
          {!revisionsResult?.revisions.length && (
            <span style={{ color: 'var(--color-text-muted)' }}>기록된 이력이 없습니다.</span>
          )}
        </div>
      </details>
      <div style={{ flexShrink: 0 }}>
        <ViewModeToggle showJson={showJson} onChange={onShowJsonChange} />
      </div>
      {showJson ? (
        <pre style={{
          flex: 1, minHeight: 0, overflow: 'auto', fontSize: 12, lineHeight: 1.6,
          fontFamily: 'monospace', color: '#1e2124', background: '#f8fafc',
          border: '1px solid #e2e8f0', borderRadius: 'var(--radius-sm)',
          padding: 'var(--space-3)', whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0,
        }}>
          {toBlocksJson(editedContent)}
        </pre>
      ) : (
        <div className="textarea-wrap" style={{ flex: 1, minHeight: 0 }}>
          <textarea
            className="krds-input"
            value={editedContent}
            onChange={(e) => onEditedContentChange(e.target.value)}
            style={{
              width: '100%', height: '100%', boxSizing: 'border-box', fontSize: 13, lineHeight: 1.7,
              fontFamily: 'inherit', color: '#1e2124', resize: 'none',
            }}
          />
        </div>
      )}
      {reprocess.isError && (
        <p style={{ color: '#dc2626', fontSize: 13, marginTop: 'var(--space-3)', flexShrink: 0 }}>
          재처리를 시작하지 못했습니다.
        </p>
      )}
    </div>
  )
}
