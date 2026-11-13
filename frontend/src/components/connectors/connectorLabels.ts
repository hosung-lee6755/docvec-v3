import type { AclMode, ConnectorStatus, LevelRule } from '../../hooks/useConnectors'
import type { BadgeTone } from '../ui/classes'
import { describeError } from '../../lib/apiError'

// 원천 연결 화면에서 쓰는 사람이 읽는 이름표. 값의 정본은 백엔드 sync_engine과 acl_mapping이다.

export const ACL_MODE_LABELS: Record<AclMode, string> = {
  file_acl: '파일 서버 권한을 따름',
  collection_only: '컬렉션 권한만 적용',
}

export const STATUS_LABELS: Record<ConnectorStatus, string> = {
  running: '동기화 중',
  success: '성공',
  partial: '일부 오류',
  failed: '실패',
}

export const STATUS_TONE: Record<ConnectorStatus, BadgeTone> = {
  running: 'info',
  success: 'success',
  partial: 'warning',
  failed: 'danger',
}

const REASON_LABELS: Record<string, string> = {
  deny_ace: '거부(Deny) 권한이 있어 그대로 옮길 수 없습니다',
  no_mapped_principal: '권한을 가진 사용자·그룹이 v3에 없습니다',
  unsupported_ace: '해석할 수 없는 권한 항목이 있습니다',
  bad_descriptor: '보안 설명자를 해석하지 못했습니다',
  descriptor_unreadable: '파일 권한을 읽지 못해 가져온 문서를 내렸습니다',
  access_sync_failed: '권한은 바뀌었지만 검색 사본을 고치지 못했습니다. 다음 동기화 때 다시 시도합니다',
  too_large: '파일이 너무 커서 건너뛰었습니다',
}

export function reasonLabel(reason: string | null): string {
  if (!reason) return '알 수 없는 이유'
  if (reason.startsWith('read_error:')) return `파일을 읽지 못했습니다(${reason.slice('read_error:'.length)})`
  return REASON_LABELS[reason] ?? reason
}

export const COUNT_LABELS: Record<string, string> = {
  added: '추가',
  content_changed: '내용 변경',
  acl_changed: '권한 변경',
  unchanged: '변화 없음',
  deleted: '삭제',
  held: '보류',
  skipped: '건너뜀',
  deferred: '다음으로 미룸',
  errors: '오류',
}

export function formatDateTime(value: string | null): string {
  if (!value) return '-'
  return new Date(value).toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' })
}

// 실패 원인까지 붙인 문장. 원인 해석은 lib/apiError.ts 한 곳에서 한다.
export function errorMessage(error: unknown, fallback: string): string {
  return describeError(error, fallback)
}

// 빈 접두어 규칙은 버리고 앞뒤 공백을 지운다
export function cleanRules(rules: LevelRule[]): LevelRule[] {
  return rules.map((r) => ({ ...r, prefix: r.prefix.trim() })).filter((r) => r.prefix)
}
