import { useState } from 'react'
import { Users, ShieldOff, Trash2 } from 'lucide-react'
import { useUsers, useUpdateUser, useDeleteUser } from '../hooks/useUsers'
import { useAuthStore } from '../store/authStore'
import { SECURITY_LEVELS, SECURITY_LEVEL_LABELS } from '../hooks/useAccess'
import type { SecurityLevel } from '../hooks/useDocumentMetadata'
import { ROLE_LABELS } from '../lib/roleLabels'
import { Badge, Button, EmptyState, ErrorAlert, IconButton, Page, PageBody, PageHeader, Select, Spinner, Stat, StatStrip } from '../components/ui'

const SYSTEM_USER_ID = '00000000-0000-0000-0000-000000000001'


export default function UsersPage() {
  const currentUser = useAuthStore((s) => s.user)
  const { data, isLoading, isError, error, refetch } = useUsers()
  const updateUser = useUpdateUser()
  const deleteUser = useDeleteUser()
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  if (currentUser?.role !== 'admin') {
    return (
      <Page>
        <EmptyState icon={<ShieldOff size={48} aria-hidden="true" />} title="관리자만 접근할 수 있습니다." />
      </Page>
    )
  }

  const users = data?.items ?? []
  const adminCount = users.filter((u) => u.role === 'admin').length
  const inactiveCount = users.filter((u) => !u.is_active).length

  const handleRoleChange = (id: string, role: 'viewer' | 'editor' | 'admin') => {
    updateUser.mutate({ id, payload: { role } })
  }

  const handleClearanceChange = (id: string, clearance_level: SecurityLevel) => {
    updateUser.mutate({ id, payload: { clearance_level } })
  }

  const handleToggleActive = (id: string, is_active: boolean) => {
    updateUser.mutate({ id, payload: { is_active } })
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteUser.mutateAsync(id)
      setConfirmDeleteId(null)
    } catch {
      // 실패 원인은 목록 위 알림이 보여 준다
    }
  }

  return (
    <Page>
      <PageHeader title="사용자 관리" subtitle="역할, 열람등급, 사용 여부를 관리합니다." />
      <StatStrip>
        <Stat label="전체 사용자" value={users.length} />
        <Stat label="관리자" value={adminCount} />
        <Stat label="비활성" value={inactiveCount} tone={inactiveCount > 0 ? 'warning' : 'default'} />
      </StatStrip>

      <PageBody>
        {updateUser.isError && <ErrorAlert error={updateUser.error} message="사용자 정보를 바꾸지 못했습니다." />}
        {deleteUser.isError && <ErrorAlert error={deleteUser.error} message="사용자를 삭제하지 못했습니다." />}
        {isLoading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
            <Spinner />
          </div>
        )}

        {isError && <ErrorAlert error={error} message="사용자 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}

        {!isLoading && !isError && users.length === 0 && (
          <EmptyState icon={<Users size={48} aria-hidden="true" />} title="사용자가 없습니다." />
        )}

        {!isLoading && !isError && users.length > 0 && (
          <div className="ds-table-wrap">
            <table className="ds-table">
              <caption className="sr-only">사용자 목록</caption>
              <thead>
                <tr>
                  <th scope="col">이메일</th>
                  <th scope="col">이름</th>
                  <th scope="col">역할</th>
                  <th scope="col" title="볼 수 있는 문서 보안등급의 상한">열람등급</th>
                  <th scope="col">활성</th>
                  <th scope="col">가입일</th>
                  <th scope="col"><span className="sr-only">작업</span></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  // 원천 연결용 내부 계정(auth_source=system)도 시스템 계정처럼 고칠 수 없다
                  const isSystem = u.id === SYSTEM_USER_ID || u.auth_source === 'system'
                  const isDirectory = u.auth_source === 'ldap'
                  const isSelf = u.id === currentUser?.id
                  const isProtected = isSystem || isSelf
                  // AD 계정의 사용 여부와 관리자 지정은 AD가 정한다(서버도 409로 막는다)
                  const isAdminLocked = isDirectory && u.role === 'admin'

                  return (
                    <tr key={u.id} className={u.is_active ? undefined : 'is-warning'}>
                      <td>
                        <span style={{ fontWeight: 500 }}>{u.email}</span>
                        <span style={{ display: 'inline-flex', gap: 4, marginLeft: 'var(--space-2)' }}>
                          {isSystem && (
                            <Badge tone="neutral">{u.auth_source === 'system' ? '원천 연결' : 'SYSTEM'}</Badge>
                          )}
                          {isDirectory && (
                            <Badge tone="info" title="사내 AD 계정입니다. 비밀번호, 소속 그룹, 퇴사 처리는 AD를 따릅니다.">AD</Badge>
                          )}
                          {isSelf && <Badge tone="info">나</Badge>}
                        </span>
                      </td>
                      <td className="ds-cell-muted">{u.username}</td>
                      <td>
                        <Select
                          controlSize="sm"
                          aria-label={`${u.email} 역할`}
                          value={u.role}
                          disabled={isProtected || isAdminLocked || updateUser.isPending}
                          title={isDirectory ? '관리자 지정은 AD 관리자 그룹 구성원으로 정합니다.' : undefined}
                          onChange={(e) => handleRoleChange(u.id, e.target.value as 'viewer' | 'editor' | 'admin')}
                        >
                          <option value="viewer">{ROLE_LABELS.viewer}</option>
                          <option value="editor">{ROLE_LABELS.editor}</option>
                          <option value="admin" disabled={isDirectory && !isAdminLocked}>{ROLE_LABELS.admin}</option>
                        </Select>
                      </td>
                      <td>
                        <Select
                          controlSize="sm"
                          value={u.clearance_level}
                          disabled={isSystem || updateUser.isPending}
                          onChange={(e) => handleClearanceChange(u.id, e.target.value as SecurityLevel)}
                          aria-label={`${u.email} 열람등급`}
                        >
                          {SECURITY_LEVELS.map((level) => (
                            <option key={level} value={level}>{SECURITY_LEVEL_LABELS[level]}</option>
                          ))}
                        </Select>
                      </td>
                      <td>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={isProtected || isDirectory || updateUser.isPending}
                          title={isDirectory ? 'AD 계정의 사용 중지는 AD에서 합니다.' : undefined}
                          onClick={() => handleToggleActive(u.id, !u.is_active)}
                        >
                          <Badge tone={u.is_active ? 'success' : 'neutral'} hasDot>
                            {u.is_active ? '활성' : '비활성'}
                          </Badge>
                        </Button>
                      </td>
                      <td className="ds-cell-muted" style={{ whiteSpace: 'nowrap' }}>
                        {new Date(u.created_at).toLocaleDateString('ko-KR')}
                      </td>
                      <td>
                        {isProtected ? null : confirmDeleteId === u.id ? (
                          <span style={{ display: 'inline-flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>삭제하시겠습니까?</span>
                            <Button variant="danger-solid" size="sm" disabled={deleteUser.isPending} onClick={() => handleDelete(u.id)}>
                              확인
                            </Button>
                            <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteId(null)}>취소</Button>
                          </span>
                        ) : (
                          <IconButton tone="danger" label={`${u.email} 삭제`} onClick={() => setConfirmDeleteId(u.id)}>
                            <Trash2 size={14} aria-hidden="true" />
                          </IconButton>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </PageBody>
    </Page>
  )
}
