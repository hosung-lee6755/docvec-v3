import { useState } from 'react'
import { Loader2, UserMinus, UserPlus } from 'lucide-react'
import type { Collection } from '../../hooks/useCollections'
import {
  useCollectionMembers,
  useInviteMember,
  useRemoveMember,
  useUpdateCollection,
} from '../../hooks/useCollections'
import { Alert, Badge, Button, Field, IconButton, Input, Modal, Select, Spinner } from '../ui'

type InviteRole = 'viewer' | 'editor'

const ROLE_LABELS: Record<string, string> = { owner: '소유자', editor: '편집자', viewer: '조회자' }

interface CollectionShareModalProps {
  collection: Collection
  onClose: () => void
}

function MemberRows({ collectionId }: { collectionId: string }) {
  const { data: memberData, isLoading: membersLoading } = useCollectionMembers(collectionId)
  const removeMember = useRemoveMember()
  const [confirmRemoveUserId, setConfirmRemoveUserId] = useState<string | null>(null)
  const members = memberData?.items ?? []

  if (membersLoading) {
    return <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-4)' }}><Spinner /></div>
  }
  if (members.length <= 1) {
    return (
      <p style={{
        margin: 0, padding: 'var(--space-4)', textAlign: 'center', fontSize: 'var(--text-sm)',
        color: 'var(--color-text-muted)', background: 'var(--color-surface-subtle)', borderRadius: 'var(--radius-md)',
      }}>
        아직 초대한 멤버가 없습니다. 위에서 이메일로 초대해 보세요.
      </p>
    )
  }
  return (
    <div className="ds-table-wrap">
      <table className="ds-table ds-table--compact" aria-label="컬렉션 멤버">
        <thead>
          <tr>
            <th scope="col">사용자</th>
            <th scope="col">권한</th>
            <th scope="col"><span className="sr-only">작업</span></th>
          </tr>
        </thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.user_id}>
              <td>
                {m.username || m.email}
                <span className="ds-cell-sub">{m.email}</span>
              </td>
              <td><Badge tone="info">{ROLE_LABELS[m.role] ?? m.role}</Badge></td>
              <td>
                {m.role !== 'owner' && (
                  confirmRemoveUserId === m.user_id ? (
                    <span style={{ display: 'inline-flex', gap: 'var(--space-2)', alignItems: 'center', whiteSpace: 'nowrap' }}>
                      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>제거할까요?</span>
                      <Button size="sm" variant="danger" disabled={removeMember.isPending} onClick={async () => {
                        await removeMember.mutateAsync({ collectionId, userId: m.user_id })
                        setConfirmRemoveUserId(null)
                      }}>
                        확인
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmRemoveUserId(null)}>취소</Button>
                    </span>
                  ) : (
                    <IconButton label="멤버 제거" tone="danger" onClick={() => setConfirmRemoveUserId(m.user_id)}>
                      <UserMinus size={16} aria-hidden="true" />
                    </IconButton>
                  )
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 컬렉션 공유 창. 열릴 때마다 새로 마운트되어 초대 입력과 메시지가 초기화된다. */
export function CollectionShareModal({ collection, onClose }: CollectionShareModalProps) {
  const updateCollection = useUpdateCollection()
  const inviteMember = useInviteMember()
  const [shareRestrict, setShareRestrict] = useState(collection.restrict_to_members)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<InviteRole>('viewer')
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [inviteSuccess, setInviteSuccess] = useState<string | null>(null)

  const handleToggleRestrict = async () => {
    const next = !shareRestrict
    await updateCollection.mutateAsync({ id: collection.id, name: collection.name, restrict_to_members: next })
    setShareRestrict(next)
  }

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inviteEmail.trim()) return
    setInviteError(null)
    setInviteSuccess(null)
    try {
      const invitedEmail = inviteEmail.trim()
      const invitedRoleLabel = inviteRole === 'editor' ? '편집자' : '조회자'
      await inviteMember.mutateAsync({ collectionId: collection.id, email: invitedEmail, role: inviteRole })
      setInviteEmail('')
      setInviteRole('viewer')
      setInviteSuccess(`${invitedEmail}님을 ${invitedRoleLabel}로 초대했습니다.`)
    } catch {
      setInviteError('초대에 실패했습니다. 가입된 사용자의 이메일인지 확인하세요.')
    }
  }

  return (
    <Modal
      isOpen
      size="md"
      isDismissible={false}
      title="컬렉션 공유"
      onClose={onClose}
      footer={<Button variant="secondary" onClick={onClose}>닫기</Button>}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
        <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>{collection.name}</p>

        {collection.project_id && (
          <label style={{
            display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)', padding: 'var(--space-3)',
            background: 'var(--color-surface-subtle)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)',
            fontSize: 'var(--text-sm)', lineHeight: 1.5, cursor: 'pointer',
          }}>
            <input
              type="checkbox"
              id="restrict_to_members"
              checked={shareRestrict}
              onChange={handleToggleRestrict}
              disabled={updateCollection.isPending}
              style={{ marginTop: 3, flexShrink: 0 }}
            />
            <span>
              <strong>이 컬렉션만 별도로 공유 범위 제한</strong>
              <br />
              <span style={{ color: 'var(--color-text-muted)' }}>
                켜면 프로젝트 멤버 전체 자동 접근이 꺼지고, 아래에서 초대한 멤버만 접근할 수 있습니다.
                (프로젝트 전체 인원 중 일부를 제외하고 싶을 때 사용)
              </span>
            </span>
          </label>
        )}

        <form onSubmit={handleInvite} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <Field label="이메일로 초대">
            {(id) => (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
                <Input
                  id={id}
                  type="email"
                  style={{ flex: '1 1 auto' }}
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="user@example.com"
                  required
                />
                <Select
                  aria-label="초대할 권한"
                  style={{ flex: '0 0 128px', width: 128 }}
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as InviteRole)}
                >
                  <option value="viewer">조회자</option>
                  <option value="editor">편집자</option>
                </Select>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={inviteMember.isPending || !inviteEmail.trim()}
                  icon={inviteMember.isPending
                    ? <Loader2 size={14} aria-hidden="true" style={{ animation: 'spin 1s linear infinite' }} />
                    : <UserPlus size={14} aria-hidden="true" />}
                >
                  초대
                </Button>
              </div>
            )}
          </Field>

          <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
            <strong>조회자</strong>는 문서 검색·열람만 가능하고, <strong>편집자</strong>는 문서 업로드도 할 수 있습니다.
            컬렉션 삭제·설정 변경·멤버 관리는 소유자만 할 수 있습니다.
          </p>

          {inviteError && <Alert tone="danger">{inviteError}</Alert>}
          {inviteSuccess && <Alert tone="success">{inviteSuccess}</Alert>}
        </form>

        <section style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, margin: 0 }}>멤버</h3>
          <MemberRows collectionId={collection.id} />
        </section>
      </div>
    </Modal>
  )
}
