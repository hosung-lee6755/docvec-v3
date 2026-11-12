// FastAPI 오류 응답의 detail을 화면에 보여줄 문장으로 바꾼다.
// detail이 문자열이면 그대로, 422 검증 오류처럼 배열이면 메시지를 이어 붙인다.
export function apiErrorDetail(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item as { msg?: unknown })?.msg)
      .filter((msg): msg is string => typeof msg === 'string')
    if (messages.length) return messages.join(' ')
  }
  return fallback
}
