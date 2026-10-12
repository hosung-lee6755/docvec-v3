import { AlertTriangle, Loader2 } from 'lucide-react'
import type { TabKey } from './documentDetailHelpers'
import type { QualityReport } from '../../hooks/useDocumentRuns'
import type { useCancelRun, useResumeRun } from '../../hooks/useWorkflows'
import { QUALITY_CRITERIA, QUALITY_DISCLAIMER, QUALITY_OVERALL_RULES } from './qualityCriteria'
import { qualityStatusDisplay, QUALITY_CATEGORY_LABELS, qualityEvidenceText, QUALITY_WARNING_TAB } from './documentDetailHelpers'

interface QualityTabProps {
  qualityReport: QualityReport | null | undefined
  isWaitingReview: boolean
  latestRun: { id: string } | null
  cancelRun: ReturnType<typeof useCancelRun>
  resumeRun: ReturnType<typeof useResumeRun>
  onHighlightChunkIdsChange: (ids: string[] | null) => void
  onActivateTab: (tab: TabKey) => void
}

const TABS: { key: string; label: string }[] = [
  { key: 'original', label: '원문 대조' },
  { key: 'structure', label: '구조' },
  { key: 'elements', label: '요소' },
  { key: 'cleaning', label: '정제 비교' },
  { key: 'dictionary', label: '사전 적용' },
  { key: 'pii', label: '민감정보' },
  { key: 'chunks', label: '청크' },
  { key: 'tables', label: '표' },
  { key: 'images', label: '그림' },
  { key: 'edit', label: 'RAG 데이터 수정' },
  { key: 'quality', label: '품질' },
  { key: 'history', label: '처리 이력' },
]

export default function QualityTab({
  qualityReport,
  isWaitingReview,
  latestRun,
  cancelRun,
  resumeRun,
  onHighlightChunkIdsChange,
  onActivateTab,
}: QualityTabProps) {
  if (!qualityReport) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
        아직 품질 리포트가 없습니다.
      </p>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
        <span style={{ fontSize: 32, fontWeight: 700 }}>
          {qualityReport.overall_score != null ? qualityReport.overall_score.toFixed(1) : '-'}
        </span>
        <span className={`krds-badge small ${qualityStatusDisplay(qualityReport.status, qualityReport.warnings?.length ?? 0).badgeClass}`}>
          {qualityStatusDisplay(qualityReport.status, qualityReport.warnings?.length ?? 0).label}
        </span>
      </div>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0, lineHeight: 1.5 }}>
        {QUALITY_DISCLAIMER}
      </p>
      <details>
        <summary style={{ fontSize: 13, fontWeight: 600, cursor: 'pointer', userSelect: 'none' }}>
          점수는 어떻게 계산되나요? (산정 기준 보기)
        </summary>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', marginTop: 'var(--space-2)' }}>
          {QUALITY_CRITERIA.map((c) => (
            <div key={c.key} style={{ fontSize: 12, lineHeight: 1.6 }}>
              <strong>{c.label}</strong>
              <span className="krds-badge small bg-gray" style={{ marginLeft: 6 }}>{c.basis}</span>
              <div>{c.how}</div>
              <div style={{ color: 'var(--color-text-muted)' }}>보지 않는 것·한계: {c.limits}</div>
            </div>
          ))}
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, lineHeight: 1.6 }}>
            {QUALITY_OVERALL_RULES.map((rule) => <li key={rule}>{rule}</li>)}
          </ul>
        </div>
      </details>
      {qualityReport.scores && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {Object.entries(qualityReport.scores).map(([category, score]) => (
            <div key={category}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                <span style={{ fontSize: 12, width: 120, flexShrink: 0, color: 'var(--color-text-muted)' }}>
                  {QUALITY_CATEGORY_LABELS[category] ?? category}
                </span>
                <div style={{ flex: 1, height: 8, background: '#e2e8f0', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{
                    width: `${Math.max(0, Math.min(100, score))}%`, height: '100%',
                    background: score >= 70 ? '#16a34a' : score >= 40 ? '#d97706' : '#dc2626',
                  }} />
                </div>
                <span style={{ fontSize: 12, width: 36, textAlign: 'right' }}>{score.toFixed(0)}</span>
              </div>
              {qualityReport.metrics && (
                <p style={{ fontSize: 11, color: 'var(--color-text-muted)', margin: '2px 0 0 132px' }}>
                  {qualityEvidenceText(category, qualityReport.metrics)}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      {!!qualityReport.warnings?.length && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
          <strong style={{ fontSize: 13 }}>경고</strong>
          {qualityReport.warnings.map((w, i) => {
            const category = qualityReport.warning_categories?.[i]
            const targetTab = category ? QUALITY_WARNING_TAB[category] : undefined
            const targetChunkIds =
              category === 'chunking_short' ? qualityReport.metrics?.short_chunk_ids
              : category === 'chunking_long' ? qualityReport.metrics?.long_chunk_ids
              : undefined
            return (
              <button
                key={i}
                type="button"
                onClick={() => {
                  if (!targetTab) return
                  onHighlightChunkIdsChange(targetChunkIds?.length ? targetChunkIds : null)
                  onActivateTab(targetTab)
                }}
                disabled={!targetTab}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#b45309',
                  background: 'none', border: 'none', padding: 0, textAlign: 'left', width: '100%',
                  cursor: targetTab ? 'pointer' : 'default',
                }}
              >
                <AlertTriangle size={13} style={{ flexShrink: 0 }} />
                <span style={{ flex: 1 }}>{String(w)}</span>
                {targetTab && (
                  <span style={{ fontSize: 11, textDecoration: 'underline', flexShrink: 0 }}>
                    {targetChunkIds?.length
                      ? '문제 청크로 이동 →'
                      : `${TABS.find((t) => t.key === targetTab)?.label ?? targetTab} 탭에서 확인 →`}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}
      {qualityReport.review_note && (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          <strong>검토 의견:</strong> {qualityReport.review_note}
        </div>
      )}
      {isWaitingReview && latestRun && (
        <div style={{ display: 'flex', gap: 'var(--space-2)', paddingTop: 'var(--space-3)', borderTop: '1px solid #e2e8f0' }}>
          <button
            onClick={() => cancelRun.mutate(latestRun.id)}
            disabled={cancelRun.isPending || resumeRun.isPending}
            className="krds-btn secondary medium"
            style={{ cursor: 'pointer' }}
          >
            반려
          </button>
          <button
            onClick={() => resumeRun.mutate(latestRun.id)}
            disabled={cancelRun.isPending || resumeRun.isPending}
            className="krds-btn primary medium"
            style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}
          >
            {resumeRun.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
            승인 후 계속 진행
          </button>
        </div>
      )}
      {(cancelRun.isError || resumeRun.isError) && (
        <p style={{ color: '#dc2626', fontSize: 12, margin: 0 }}>작업을 처리하지 못했습니다.</p>
      )}
    </div>
  )
}
