import { ErrorText, toneFromKrdsClass } from '../ui'
import { Loader2 } from 'lucide-react'
import type { TabKey } from './documentDetailHelpers'
import QualityWarningList from './QualityWarningList'
import type { QualityReport } from '../../hooks/useDocumentRuns'
import type { useCancelRun, useResumeRun } from '../../hooks/useWorkflows'
import { QUALITY_CRITERIA, QUALITY_DISCLAIMER, QUALITY_OVERALL_RULES, sourceRecallSkipReason } from './qualityCriteria'
import { qualityStatusDisplay, QUALITY_CATEGORY_LABELS, qualityEvidenceText } from './documentDetailHelpers'

interface QualityTabProps {
  qualityReport: QualityReport | null | undefined
  isWaitingReview: boolean
  latestRun: { id: string } | null
  cancelRun: ReturnType<typeof useCancelRun>
  resumeRun: ReturnType<typeof useResumeRun>
  onHighlightChunkIdsChange: (ids: string[] | null) => void
  onActivateTab: (tab: TabKey) => void
}

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
        <span className={`ds-badge ds-badge--${toneFromKrdsClass(qualityStatusDisplay(qualityReport.status, qualityReport.warnings?.length ?? 0).badgeClass)}`}>
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
              <span className="ds-badge ds-badge--neutral" style={{ marginLeft: 6 }}>{c.basis}</span>
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
                <div style={{ flex: 1, height: 8, background: 'var(--color-border)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{
                    width: `${Math.max(0, Math.min(100, score))}%`, height: '100%',
                    background: score >= 70 ? 'var(--color-success)' : score >= 40 ? 'var(--color-warning-dot)' : 'var(--color-danger)',
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
      {sourceRecallSkipReason(qualityReport.metrics?.source_recall_status) && (
        <p style={{ fontSize: 11, color: 'var(--color-text-muted)', margin: 0 }}>
          원문 재현율: {sourceRecallSkipReason(qualityReport.metrics?.source_recall_status)}
        </p>
      )}
      {!!qualityReport.warnings?.length && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
          <strong style={{ fontSize: 13 }}>경고</strong>
          <QualityWarningList
            report={qualityReport}
            onHighlightChunkIdsChange={onHighlightChunkIdsChange}
            onActivateTab={onActivateTab}
          />
        </div>
      )}
      {qualityReport.review_note && (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          <strong>검토 의견:</strong> {qualityReport.review_note}
        </div>
      )}
      {isWaitingReview && latestRun && (
        <div style={{ display: 'flex', gap: 'var(--space-2)', paddingTop: 'var(--space-3)', borderTop: '1px solid var(--color-border)' }}>
          <button
            onClick={() => cancelRun.mutate(latestRun.id)}
            disabled={cancelRun.isPending || resumeRun.isPending}
            className="ds-btn ds-btn--secondary"
            style={{ cursor: 'pointer' }}
          >
            반려
          </button>
          <button
            onClick={() => resumeRun.mutate(latestRun.id)}
            disabled={cancelRun.isPending || resumeRun.isPending}
            className="ds-btn ds-btn--primary"
            style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}
          >
            {resumeRun.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
            승인 후 계속 진행
          </button>
        </div>
      )}
      {(cancelRun.isError || resumeRun.isError) && (
        <p style={{ margin: 0 }}>
          {cancelRun.isError && <ErrorText error={cancelRun.error} message="실행을 취소하지 못했습니다." />}
          {resumeRun.isError && <ErrorText error={resumeRun.error} message="실행을 재개하지 못했습니다." />}
        </p>
      )}
    </div>
  )
}
