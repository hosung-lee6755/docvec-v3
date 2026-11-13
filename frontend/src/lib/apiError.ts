// 요청이 실패한 원인을 사용자가 알아들을 수 있는 한국어 문장으로 바꾼다.
// 화면은 "무엇을 못 했는지"만 정하고, "왜"는 이 파일 한 곳에서 정한다.
import { isAxiosError } from 'axios'

const HANGUL = /[가-힣]/

// 백엔드가 영어로 주는 "<대상> not found"의 대상 이름과 목적격 조사
const NOT_FOUND_TARGETS: Record<string, string> = {
  document: '문서를',
  project: '프로젝트를',
  collection: '컬렉션을',
  user: '사용자를',
  group: '그룹을',
  'group member': '그룹 구성원을',
  workflow: '워크플로우를',
  version: '버전을',
  run: '실행 기록을',
  revision: '리비전을',
  node: '블록을',
  chunk: '청크를',
  'pii detection': '민감정보 탐지 결과를',
}

const STATUS_CAUSES: Record<number, string> = {
  400: '요청 내용이 올바르지 않습니다. 입력값을 확인하세요.',
  401: '로그인이 만료되었습니다. 다시 로그인하세요.',
  403: '이 작업을 할 권한이 없습니다. 필요하면 관리자에게 권한을 요청하세요.',
  404: '대상을 찾을 수 없습니다. 이미 삭제되었거나 볼 수 있는 권한이 바뀌었을 수 있습니다.',
  409: '다른 작업과 겹쳤습니다. 화면을 새로고침한 뒤 다시 시도하세요.',
  413: '파일이나 요청이 너무 큽니다. 크기를 줄여 다시 시도하세요.',
  422: '입력값이 올바르지 않습니다. 입력한 내용을 확인하세요.',
  429: '요청이 너무 많습니다. 잠시 뒤 다시 시도하세요.',
}

const NETWORK_CAUSE = '서버에 연결할 수 없습니다. 네트워크 연결을 확인하거나 잠시 뒤 다시 시도하세요.'
const TIMEOUT_CAUSE = '서버 응답이 너무 늦습니다. 잠시 뒤 다시 시도하세요.'
const UNAVAILABLE_CAUSE = '서버가 응답하지 않습니다. 점검 중이거나 다시 시작하는 중일 수 있으니 잠시 뒤 다시 시도하세요.'
const UNKNOWN_CAUSE = '알 수 없는 문제가 생겼습니다. 잠시 뒤 다시 시도하고, 계속되면 관리자에게 알려 주세요.'

function notFoundCause(detail: string): string | null {
  const match = /^(.+) not found$/i.exec(detail.trim())
  const target = match ? NOT_FOUND_TARGETS[match[1].toLowerCase()] : undefined
  if (!target) return null
  return `${target} 찾을 수 없습니다. 이미 삭제되었거나 볼 수 있는 권한이 바뀌었을 수 있습니다.`
}

// 422 검증 오류: 한국어 메시지가 있으면 그것을, 없으면 문제가 된 입력 칸 이름을 알린다
function validationCause(detail: unknown[]): string | null {
  const korean = detail
    .map((item) => (item as { msg?: unknown })?.msg)
    .filter((msg): msg is string => typeof msg === 'string' && HANGUL.test(msg))
  if (korean.length) return korean.join(' ')
  const fields = detail
    .map((item) => {
      const loc = (item as { loc?: unknown })?.loc
      return Array.isArray(loc) && loc.length ? String(loc[loc.length - 1]) : null
    })
    .filter((field): field is string => !!field)
  if (!fields.length) return null
  return `입력값이 올바르지 않습니다. 다음 항목을 확인하세요: ${[...new Set(fields)].join(', ')}`
}

function detailCause(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) {
    return HANGUL.test(detail) ? detail.trim() : notFoundCause(detail)
  }
  if (Array.isArray(detail)) return validationCause(detail)
  return null
}

function statusCause(status: number): string {
  if (status === 502 || status === 503 || status === 504) return UNAVAILABLE_CAUSE
  if (status >= 500) return `서버에서 오류가 났습니다. 계속되면 관리자에게 알려 주세요. (오류 코드 ${status})`
  return STATUS_CAUSES[status] ?? `요청을 처리하지 못했습니다. (오류 코드 ${status})`
}

/** 실패 원인 한 문장. 원인을 모르면 일반 안내를 돌려준다(빈 문자열은 없다). */
export function errorCause(error: unknown): string {
  if (isAxiosError(error)) {
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') return TIMEOUT_CAUSE
    if (!error.response) return NETWORK_CAUSE
    const data = error.response.data as { detail?: unknown } | undefined
    return detailCause(data?.detail) ?? statusCause(error.response.status)
  }
  if (error instanceof Error && HANGUL.test(error.message)) return error.message
  return UNKNOWN_CAUSE
}

// 백그라운드 작업(문서 처리, 답변 생성, 워크플로우 실행)이 남긴 영어·기술 메시지를 알아볼 수 있는 원인으로 바꾼다
const FAILURE_PATTERNS: Array<[RegExp, string]> = [
  [/timed? ?out|timeout|deadline exceeded/i, '처리 시간이 초과되었습니다. 문서가 크거나 서버가 바쁠 수 있으니 잠시 뒤 다시 시도하세요.'],
  [/connection refused|connecterror|connection (reset|error|aborted)|name or service not known|unreachable/i, '모델 서버나 외부 서비스에 연결하지 못했습니다. 서비스가 켜져 있는지 관리자에게 확인하세요.'],
  [/api[ _-]?key|authenticationerror|unauthorized|\b401\b/i, 'API 키가 없거나 올바르지 않습니다. 설정 화면에서 API 키를 확인하세요.'],
  [/rate ?limit|too many requests|\b429\b|quota/i, '외부 모델의 사용 한도를 넘었습니다. 잠시 뒤 다시 시도하거나 사용 한도를 확인하세요.'],
  [/out of memory|outofmemory|\boom\b|cuda error/i, '서버 메모리(GPU)가 부족합니다. 다른 작업이 끝난 뒤 다시 시도하세요.'],
  [/no space left|disk full/i, '서버 저장 공간이 부족합니다. 관리자에게 알려 주세요.'],
  [/permission denied|forbidden|\b403\b/i, '작업에 필요한 권한이 없습니다. 관리자에게 권한을 확인하세요.'],
  [/not found|no such file|\b404\b/i, '작업에 필요한 파일이나 대상을 찾지 못했습니다. 원본이 삭제되었는지 확인하세요.'],
  [/encrypt|password[- ]protected|decrypt/i, '암호가 걸린 파일이라 열 수 없습니다. 암호를 푼 파일로 다시 올려 주세요.'],
  [/corrupt|invalid pdf|cannot (open|read)|unsupported (file|format)|malformed/i, '파일이 손상되었거나 지원하지 않는 형식이라 읽지 못했습니다.'],
]

/** 서버 작업이 남긴 실패 메시지를 사용자가 알아볼 수 있는 원인 문장으로 바꾼다. */
export function explainFailure(message: string | null | undefined): string {
  const text = message?.trim()
  if (!text) return '원인이 기록되지 않았습니다. 다시 시도하고, 계속되면 관리자에게 알려 주세요.'
  if (HANGUL.test(text)) return text
  const hit = FAILURE_PATTERNS.find(([pattern]) => pattern.test(text))
  if (hit) return hit[1]
  return `서버 작업 중 예상하지 못한 오류가 났습니다. 계속되면 관리자에게 아래 내용을 알려 주세요. (${text})`
}

/** "무엇을 못 했는지" 다음에 원인을 붙인 문장 */
export function describeError(error: unknown, what: string): string {
  return `${what} ${errorCause(error)}`
}

/** 예전 이름. describeError와 같다. */
export function apiErrorDetail(error: unknown, fallback: string): string {
  return describeError(error, fallback)
}
