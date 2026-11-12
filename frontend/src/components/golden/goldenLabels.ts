import type { GoldenRegressedMetric, GoldenRunStatus, GoldenRunTrigger } from '../../hooks/useGoldenQueries'

export const RUN_STATUS_LABELS: Record<GoldenRunStatus, string> = {
  QUEUED: '대기 중',
  RUNNING: '평가 중',
  DONE: '완료',
  FAILED: '실패',
}

export const RUN_TRIGGER_LABELS: Record<GoldenRunTrigger, string> = {
  manual: '수동 실행',
  search_settings: '검색 설정 변경',
  dictionary: '사전 변경',
  new_version: '새 버전 반영',
  lifecycle: '보관·되돌리기·만료',
  document_deleted: '문서 삭제',
}

export const REGRESSED_METRIC_LABELS: Record<GoldenRegressedMetric, string> = {
  mean_hit_rate: '적중률',
  mean_recall: '평균 재현율',
  mean_mrr: 'MRR',
}

export function formatPercent(value: number | null | undefined): string {
  return value == null ? '-' : `${(value * 100).toFixed(1)}%`
}
