// 알림처럼 "얼마 전"으로 보여 주는 시각 표시(전체 점검 2-7)

const MINUTE_MS = 60_000
const HAS_TIMEZONE = /(Z|[+-]\d\d:\d\d)$/i

export function formatElapsed(createdAt: string, now: number = Date.now()): string {
  // 서버는 시간대 표시 없이 UTC로 준다
  const created = new Date(HAS_TIMEZONE.test(createdAt) ? createdAt : `${createdAt}Z`).getTime()
  const minutes = Math.max(0, Math.floor((now - created) / MINUTE_MS))
  if (minutes < 1) return '방금'
  if (minutes < 60) return `${minutes}분 전`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}시간 전`
  return `${Math.floor(hours / 24)}일 전`
}
