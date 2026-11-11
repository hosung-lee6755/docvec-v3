import { useState } from 'react'
import { Lock, LockOpen, X } from 'lucide-react'
import {
  SECURITY_LEVEL_LABELS, useDocumentAcl, useGroups, useReplaceDocumentAcl,
} from '../../hooks/useAccess'
import type { AclEntry, PrincipalType } from '../../hooks/useAccess'
import { useCollectionMembers } from '../../hooks/useCollections'
import { Row } from './documentDetailParts'

// v3 문서 접근 허용 목록 — 문서 편집 권한이 있는 사용자에게만 보인다(API가 403이면 숨김).
// 목록이 비어 있으면 컬렉션 권한·보안등급만 적용되고, 항목이 있으면 목록의 사용자·그룹과
// 업로더 본인만 볼 수 있다.

interface AccessPanelProps {
  documentId: string
  collectionId: string | null
  securityLevel: string | null
}

const PRINCIPAL_LABEL: Record<PrincipalType, string> = { user: '사용자', group: '그룹' }

function httpStatus(error: unknown): number | undefined {
  return (error as { response?: { status?: number } })?.response?.status
}

function errorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : '허용 목록을 저장하지 못했습니다.'
}

function entryKey(e: { principal_type: PrincipalType; principal_id: string }): string {
  return `${e.principal_type}:${e.principal_id}`
}

export default function AccessPanel({ documentId, collectionId, securityLevel }: AccessPanelProps) {
  const acl = useDocumentAcl(documentId, securityLevel)
  const groups = useGroups()
  const members = useCollectionMembers(collectionId)
  const replaceAcl = useReplaceDocumentAcl()
  const [candidate, setCandidate] = useState('')

  if (acl.isError) {
    // 403 = 편집 권한 없음 → 패널 자체를 숨긴다. 그 밖의 오류만 알린다.
    if (httpStatus(acl.error) === 403) return null
    return <Row label="접근 허용">허용 목록을 불러오지 못했습니다.</Row>
  }
  if (!acl.data) return null

  const entries = acl.data.entries
  const current = new Set(entries.map(entryKey))
  const save = (next: { principal_type: PrincipalType; principal_id: string }[]) =>
    replaceAcl.mutate({ documentId, entries: next })
  const toInput = (e: AclEntry) => ({ principal_type: e.principal_type, principal_id: e.principal_id })

  const handleAdd = () => {
    if (!candidate) return
    const [principal_type, principal_id] = candidate.split(':') as [PrincipalType, string]
    save([...entries.map(toInput), { principal_type, principal_id }])
    setCandidate('')
  }

  const groupOptions = (groups.data?.items ?? []).filter((g) => !current.has(`group:${g.id}`))
  const userOptions = (members.data?.items ?? []).filter((m) => !current.has(`user:${m.user_id}`))
  const effective = acl.data.effective_security_level
  // 접근을 넓히는 변경(제한 해제, 허용 대상 추가, 마지막 항목 제거)은 업로더·컬렉션 소유자만 할 수 있다.
  const canRelax = acl.data.can_relax ?? true
  const canAdd = canRelax || !acl.data.restricted
  const canRemove = canRelax || entries.length > 1

  return (
    <Row label="접근 허용">
      <span style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          {acl.data.restricted ? <Lock size={12} /> : <LockOpen size={12} />}
          {acl.data.restricted
            ? '아래 사용자·그룹과 업로더만 볼 수 있습니다'
            : '제한 없음 — 컬렉션 권한과 보안등급만 적용'}
          {' · 적용 등급 '}
          <strong>{SECURITY_LEVEL_LABELS[effective]}</strong>
          {!acl.data.security_level && ' (컬렉션 기본값)'}
        </span>

        {entries.length > 0 && (
          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
            {entries.map((e) => (
              <span key={entryKey(e)} className="krds-badge small bg-information" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                {PRINCIPAL_LABEL[e.principal_type]} · {e.display_name ?? `삭제된 ${PRINCIPAL_LABEL[e.principal_type]}`}
                <button
                  type="button"
                  aria-label={`${e.display_name ?? e.principal_id} 허용 해제`}
                  disabled={replaceAcl.isPending || !canRemove}
                  onClick={() => save(entries.filter((x) => entryKey(x) !== entryKey(e)).map(toInput))}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'inherit', lineHeight: 1 }}
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </span>
        )}

        <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <select
            value={candidate}
            onChange={(e) => setCandidate(e.target.value)}
            aria-label="허용 목록에 추가할 사용자 또는 그룹"
            style={{ fontSize: 12, border: '1px solid #e2e8f0', borderRadius: 4, padding: '2px 6px', maxWidth: 220 }}
          >
            <option value="">사용자·그룹 추가…</option>
            {groupOptions.length > 0 && (
              <optgroup label="그룹">
                {groupOptions.map((g) => <option key={g.id} value={`group:${g.id}`}>{g.name}</option>)}
              </optgroup>
            )}
            {userOptions.length > 0 && (
              <optgroup label="컬렉션 멤버">
                {userOptions.map((m) => <option key={m.user_id} value={`user:${m.user_id}`}>{m.username}</option>)}
              </optgroup>
            )}
          </select>
          <button type="button" className="krds-btn xsmall secondary" disabled={!candidate || replaceAcl.isPending || !canAdd} onClick={handleAdd}>
            추가
          </button>
          {acl.data.restricted && (
            <button type="button" className="krds-btn text xsmall" disabled={replaceAcl.isPending || !canRelax} onClick={() => save([])}>
              제한 해제
            </button>
          )}
        </span>
        {!canRelax && (
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            허용 대상을 늘리거나 제한을 푸는 일은 업로더나 컬렉션 소유자만 할 수 있습니다.
          </span>
        )}
        {replaceAcl.isError && <span style={{ fontSize: 12, color: '#dc2626' }}>{errorMessage(replaceAcl.error)}</span>}
      </span>
    </Row>
  )
}
