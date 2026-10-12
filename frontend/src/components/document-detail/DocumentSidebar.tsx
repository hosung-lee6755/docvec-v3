import { Loader2 } from 'lucide-react'
import { STATUS_BADGE_CLASSES, STATUS_LABELS } from '../../lib/documentStatus'
import type { TabKey } from './documentDetailHelpers'
import { Row, CopyableValue, EditableMetaField, DateMetaField, SecurityLevelField } from './documentDetailParts'
import { qualityStatusDisplay, RUN_TRIGGER_LABELS, RUN_STATUS_BADGE } from './documentDetailHelpers'
import type { useAcceptTagSuggestion, useDismissTagSuggestion, useUpdateDocumentTags } from '../../hooks/useDocuments'
import type { useUpdateDocumentMetadata } from '../../hooks/useDocumentMetadata'
import type { Document } from '../../hooks/useDocuments'
import type { DocumentRunItem, QualityReport } from '../../hooks/useDocumentRuns'

interface DocumentSidebarProps {
  doc: Document
  isReady: boolean
  isProcessing: boolean
  isAnalyzing: boolean
  chunksResult: { chunks: { disabled: boolean; hit_count: number }[] } | undefined
  qualityReport: QualityReport | null | undefined
  latestRun: DocumentRunItem | null
  updateMetadata: ReturnType<typeof useUpdateDocumentMetadata>
  updateTags: ReturnType<typeof useUpdateDocumentTags>
  acceptSuggestion: ReturnType<typeof useAcceptTagSuggestion>
  dismissSuggestion: ReturnType<typeof useDismissTagSuggestion>
  tagInput: string
  onTagInputChange: (v: string) => void
  onActiveTabChange: (tab: TabKey) => void
}

export default function DocumentSidebar({
  doc,
  isReady,
  isProcessing,
  isAnalyzing,
  chunksResult,
  qualityReport,
  latestRun,
  updateMetadata,
  updateTags,
  acceptSuggestion,
  dismissSuggestion,
  tagInput,
  onTagInputChange,
  onActiveTabChange,
}: DocumentSidebarProps) {
  return (
    <div>
      <div style={{ maxWidth: 640 }}>
        <Row label="상태">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <span className={`krds-badge small ${STATUS_BADGE_CLASSES[doc.status] ?? 'bg-gray'}`}>
              {STATUS_LABELS[doc.status] ?? doc.status}
            </span>
            {isProcessing && (
              <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                처리 중... (자동 갱신)
              </span>
            )}
          </span>
        </Row>
        <Row label="파일 크기">{(doc.file_size / 1024).toFixed(1)} KB</Row>
        <Row label="생성일">{new Date(doc.created_at).toLocaleString('ko-KR')}</Row>
        <Row label="수정일">{new Date(doc.updated_at).toLocaleString('ko-KR')}</Row>
        <Row label="제목">{doc.title || doc.original_filename}</Row>
        <Row label="언어">{doc.language ?? '미판별'}</Row>
        <Row label="분류">{doc.category ?? '미분류'}</Row>
        <Row label="페이지 수">{doc.page_count ?? '-'}</Row>
        <Row label="체크섬">
          {doc.checksum
            ? <CopyableValue value={doc.checksum} display={`${doc.checksum.slice(0, 16)}…`} />
            : '-'}
        </Row>
        <Row label="저장 경로">
          {doc.source_path
            ? <CopyableValue value={doc.source_path} display={doc.source_path} />
            : '-'}
        </Row>
        <Row label="파일 형식">{doc.file_type ?? '-'}</Row>
        <DateMetaField
          label="문서 작성일"
          value={doc.document_created_at ? doc.document_created_at.slice(0, 10) : null}
          onSave={(value) => updateMetadata.mutate({ documentId: doc.id, document_created_at: value || null })}
        />
        <EditableMetaField
          label="작성자"
          value={doc.author}
          onSave={(value) => updateMetadata.mutate({ documentId: doc.id, author: value })}
        />
        <EditableMetaField
          label="부서/기관"
          value={doc.organization}
          onSave={(value) => updateMetadata.mutate({ documentId: doc.id, organization: value })}
        />
        <SecurityLevelField
          value={doc.security_level}
          onSave={(value) => updateMetadata.mutate({ documentId: doc.id, security_level: value || null })}
        />
        <EditableMetaField
          label="출처 시스템"
          value={doc.source_system}
          onSave={(value) => updateMetadata.mutate({ documentId: doc.id, source_system: value })}
        />
        <Row label="태그">
          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            {(doc.tags ?? []).map((tag) => (
              <span key={tag} className="krds-badge small bg-information" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                {tag}
                <button
                  onClick={() => updateTags.mutate({ docId: doc.id, tags: (doc.tags ?? []).filter((t) => t !== tag) })}
                  aria-label={`태그 ${tag} 삭제`}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'inherit', lineHeight: 1 }}
                >
                  ×
                </button>
              </span>
            ))}
            <input
              id="document_tag_input"
              name="document_tag_input"
              value={tagInput}
              onChange={(e) => onTagInputChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && tagInput.trim() && !e.nativeEvent.isComposing) {
                  const next = [...new Set([...(doc.tags ?? []), tagInput.trim()])]
                  updateTags.mutate({ docId: doc.id, tags: next }, {
                    onSuccess: () => onTagInputChange(''),
                  })
                }
              }}
              placeholder="태그 입력 후 Enter"
              style={{ fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4, padding: '2px 8px', width: 130 }}
            />
          </span>
        </Row>
        {doc.metadata_status === 'GENERATING' && (
          <Row label="추천 태그">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--color-text-muted)' }}>
              <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
              자동 추출 중...
            </span>
          </Row>
        )}
        {!!doc.suggested_tags?.length && (
          <Row label="추천 태그">
            <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
              {doc.suggested_tags.map((tag) => {
                const alreadyAdded = (doc.tags ?? []).includes(tag)
                return (
                  <span
                    key={tag}
                    className="krds-badge small"
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4,
                      border: alreadyAdded ? '1px solid var(--color-success, #16a34a)' : '1px dashed #94a3b8',
                      background: 'transparent', color: 'var(--color-text-muted)',
                    }}
                  >
                    {tag}
                    {alreadyAdded ? (
                      <span
                        title="이미 태그로 추가됨"
                        style={{ color: 'var(--color-success, #16a34a)', lineHeight: 1, fontWeight: 700 }}
                      >
                        ✓
                      </span>
                    ) : (
                      <button
                        onClick={() => acceptSuggestion.mutate({ docId: doc.id, tag })}
                        aria-label={`추천 태그 ${tag} 추가`}
                        title="태그로 추가"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'var(--color-success, #16a34a)', lineHeight: 1, fontWeight: 700 }}
                      >
                        +
                      </button>
                    )}
                    <button
                      onClick={() => dismissSuggestion.mutate({ docId: doc.id, tag })}
                      aria-label={`추천 태그 ${tag} 무시`}
                      title="제안 무시"
                      style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'inherit', lineHeight: 1 }}
                    >
                      ×
                    </button>
                  </span>
                )
              })}
            </span>
          </Row>
        )}
      </div>

      {isReady && (
        <div style={{ marginTop: 'var(--space-6)', maxWidth: 640 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 'var(--space-2)' }}>
            분석 요약
          </h2>
          {isAnalyzing && (doc.summary_status === 'PENDING' || doc.summary_status === 'GENERATING') && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--color-text-muted)', fontSize: 13 }}>
              <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
              문서 요약을 생성하는 중입니다...
            </div>
          )}
          {!isAnalyzing && (doc.summary_status === 'PENDING' || doc.summary_status === 'GENERATING') && (
            <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
              생성된 요약이 없습니다.
            </p>
          )}
          {doc.summary_status === 'FAILED' && (
            <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
              요약을 생성하지 못했습니다.
            </p>
          )}
          {doc.summary_status === 'DONE' && (
            <p style={{ fontSize: 13, lineHeight: 1.7, whiteSpace: 'pre-wrap', margin: 0, color: 'var(--color-accent)' }}>
              {doc.summary || '요약 내용이 없습니다.'}
            </p>
          )}
        </div>
      )}

      {(isReady || doc.status === 'WAITING_REVIEW') && (
        <div style={{ marginTop: 'var(--space-6)', maxWidth: 640 }}>
          <h2 style={{ fontSize: 14, fontWeight: 600, marginBottom: 'var(--space-2)' }}>
            RAG 현황
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ width: 64, flexShrink: 0, color: 'var(--color-text-muted)' }}>청크</span>
              {chunksResult ? (
                <>
                  <span>{chunksResult.chunks.length}개</span>
                  {chunksResult.chunks.some((c) => c.disabled) && (
                    <span style={{ color: 'var(--color-text-muted)' }}>
                      (검색 제외 {chunksResult.chunks.filter((c) => c.disabled).length}개)
                    </span>
                  )}
                  <span style={{ color: 'var(--color-text-muted)' }}>
                    · 조회 {chunksResult.chunks.reduce((sum, c) => sum + c.hit_count, 0)}회
                  </span>
                </>
              ) : (
                <span style={{ color: 'var(--color-text-muted)' }}>불러오는 중...</span>
              )}
              <button
                onClick={() => onActiveTabChange('chunks')}
                className="krds-btn text xsmall"
                style={{ padding: 0, cursor: 'pointer' }}
              >
                자세히
              </button>
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ width: 64, flexShrink: 0, color: 'var(--color-text-muted)' }}>품질</span>
              {qualityReport ? (
                <>
                  <span className={`krds-badge xsmall ${qualityStatusDisplay(qualityReport.status, qualityReport.warnings?.length ?? 0).badgeClass}`}>
                    {qualityStatusDisplay(qualityReport.status, qualityReport.warnings?.length ?? 0).label}
                  </span>
                  {qualityReport.overall_score != null && (
                    <span style={{ color: 'var(--color-text-muted)' }}>{qualityReport.overall_score.toFixed(1)}점</span>
                  )}
                  {!!qualityReport.warnings?.length && (
                    <span style={{ color: '#b45309' }}>경고 {qualityReport.warnings.length}건</span>
                  )}
                </>
              ) : (
                <span style={{ color: 'var(--color-text-muted)' }}>리포트 없음</span>
              )}
              <button
                onClick={() => onActiveTabChange('quality')}
                className="krds-btn text xsmall"
                style={{ padding: 0, cursor: 'pointer' }}
              >
                자세히
              </button>
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ width: 64, flexShrink: 0, color: 'var(--color-text-muted)' }}>최근 실행</span>
              {latestRun ? (
                <>
                  <span className={`krds-badge xsmall ${RUN_STATUS_BADGE[latestRun.status] ?? 'bg-gray'}`}>
                    {latestRun.status}
                  </span>
                  <span>{RUN_TRIGGER_LABELS[latestRun.trigger] ?? latestRun.trigger}</span>
                  <span style={{ color: 'var(--color-text-muted)' }}>
                    {latestRun.started_at ? new Date(latestRun.started_at).toLocaleString('ko-KR') : '-'}
                  </span>
                </>
              ) : (
                <span style={{ color: 'var(--color-text-muted)' }}>실행 이력 없음</span>
              )}
              <button
                onClick={() => onActiveTabChange('history')}
                className="krds-btn text xsmall"
                style={{ padding: 0, cursor: 'pointer' }}
              >
                자세히
              </button>
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
