import type { QualityReport } from '../../hooks/useDocumentRuns'
import { formatPageRanges, structureWarnings } from '../../lib/qualityTargets'
import { Alert } from '../ui'

// 쪽 단추를 이만큼만 그리고 나머지는 범위 글로 보여 준다
const MAX_PAGE_BUTTONS = 30

interface StructureWarningNoticeProps {
  report: QualityReport | null | undefined
  onViewPage: (pageNumber: number) => void
}

/** 구조 탭 위에서, 구조 경고(빈 쪽, 목차와 제목 불일치)가 어느 쪽과 어느 항목 때문인지 보여 준다. */
export default function StructureWarningNotice({ report, onViewPage }: StructureWarningNoticeProps) {
  const warnings = structureWarnings(report)
  if (!report || !warnings.length) return null
  const emptyPages = report.metrics?.empty_pages
  const tocUnmatched = report.metrics?.toc_unmatched
  const hasTargets = emptyPages !== undefined || tocUnmatched !== undefined
  return (
    <Alert tone="warning">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', fontSize: 12 }}>
        <strong style={{ fontSize: 13 }}>품질 검사의 구조 경고</strong>
        {warnings.map((warning, index) => <span key={index}>{warning}</span>)}
        {!!emptyPages?.length && (
          <div>
            <div style={{ marginBottom: 4 }}>
              글이 추출되지 않은 쪽은 {emptyPages.length}쪽입니다({formatPageRanges(emptyPages)}). 쪽 번호를 누르면
              원문 대조 탭에서 그 쪽을 엽니다. 그림이나 여러 쪽에 걸친 표만 있는 쪽이면 문제가 아닐 수 있습니다.
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {emptyPages.slice(0, MAX_PAGE_BUTTONS).map((page) => (
                <button key={page} type="button" className="ds-page-chip" onClick={() => onViewPage(page)}>
                  {page}쪽
                </button>
              ))}
              {emptyPages.length > MAX_PAGE_BUTTONS && <span>외 {emptyPages.length - MAX_PAGE_BUTTONS}쪽</span>}
            </div>
          </div>
        )}
        {!!tocUnmatched?.length && (
          <div>
            <div style={{ marginBottom: 4 }}>
              목차에는 있지만 본문에서 제목으로 잡히지 않은 항목입니다. 아래 트리에서 해당 줄을 찾아 유형을
              제목으로 고칠 수 있습니다.
            </div>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {tocUnmatched.map((entry, index) => <li key={index}>{entry}</li>)}
            </ul>
          </div>
        )}
        {!hasTargets && (
          <span>
            이 품질 보고서는 대상 목록을 남기기 전에 만들어져서 어느 쪽인지 표시할 수 없습니다. 문서를 다시
            처리하면 대상이 표시됩니다.
          </span>
        )}
      </div>
    </Alert>
  )
}
