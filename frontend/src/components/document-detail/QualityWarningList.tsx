import { AlertTriangle } from 'lucide-react'
import type { QualityReport } from '../../hooks/useDocumentRuns'
import { warningChunkIds } from '../../lib/qualityTargets'
import { QUALITY_WARNING_TAB, type TabKey } from './documentDetailHelpers'

interface QualityWarningListProps {
  report: QualityReport
  onHighlightChunkIdsChange: (ids: string[] | null) => void
  onActivateTab: (tab: TabKey) => void
}

// 경고를 누르면 어디로 가서 무엇을 보게 되는지 알려 주는 문구
function destinationHint(category: string | undefined, targetTab: TabKey, chunkCount: number): string {
  if (chunkCount > 0) return `대상 청크 ${chunkCount}개 보기 →`
  if (category === 'structure') return '구조 탭에서 대상 확인 →'
  if (targetTab === 'chunks') return '청크 탭에서 확인 →'
  return '원문 대조 탭에서 확인 →'
}

/** 품질 경고 목록. 누르면 해당 탭으로 옮기고, 청크 경고는 대상 청크를 표시하게 한다. */
export default function QualityWarningList({ report, onHighlightChunkIdsChange, onActivateTab }: QualityWarningListProps) {
  if (!report.warnings?.length) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
      {report.warnings.map((warning, index) => {
        const category = report.warning_categories?.[index]
        const targetTab = category ? QUALITY_WARNING_TAB[category] : undefined
        const targetChunkIds = warningChunkIds(category, report.metrics)
        return (
          <button
            key={index}
            type="button"
            className="ds-quality-warning"
            disabled={!targetTab}
            onClick={() => {
              if (!targetTab) return
              onHighlightChunkIdsChange(targetChunkIds?.length ? targetChunkIds : null)
              onActivateTab(targetTab)
            }}
          >
            <AlertTriangle size={13} style={{ flexShrink: 0 }} />
            <span style={{ flex: 1 }}>{String(warning)}</span>
            {targetTab && (
              <span className="ds-quality-warning__go">
                {destinationHint(category, targetTab, targetChunkIds?.length ?? 0)}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
