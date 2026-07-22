import { useState } from 'react'
import { Users, Loader2, ShieldOff, Trash2 } from 'lucide-react'
import { useUsers, useUpdateUser, useDeleteUser } from '../hooks/useUsers'
import { useAuthStore } from '../store/authStore'

const SYSTEM_USER_ID = '00000000-0000-0000-0000-000000000001'

const ROLE_LABELS: Record<string, string> = {
  admin: '관리자',
  editor: '편집자',
  viewer: '뷰어',
}

export default function UsersPage() {
  const currentUser = useAuthStore((s) => s.user)
  const { data, isLoading, isError } = useUsers()
  const updateUser = useUpdateUser()
  const deleteUser = useDeleteUser()
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  if (currentUser?.role !== 'admin') {
    return (
      <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
        <ShieldOff size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
        <p>관리자만 접근할 수 있습니다.</p>
      </div>
    )
  }

  const handleRoleChange = (id: string, role: 'viewer' | 'editor' | 'admin') => {
    updateUser.mutate({ id, payload: { role } })
  }

  const handleToggleActive = (id: string, is_active: boolean) => {
    updateUser.mutate({ id, payload: { is_active } })
  }

  const handleDelete = async (id: string) => {
    await deleteUser.mutateAsync(id)
    setConfirmDeleteId(null)
  }

  return (
    <div>
      <style>{'@keyframes spin { to { transform: rotate(360deg) } }'}</style>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>사용자 관리</h1>
      </div>

      {isLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
          <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
        </div>
      )}

      {isError && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
          color: '#dc2626', marginBottom: 'var(--space-4)',
        }}>
          사용자 목록을 불러오지 못했습니다.
        </div>
      )}

      {!isLoading && !isError && (data?.items.length ?? 0) === 0 && (
        <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
          <Users size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
          <p>사용자가 없습니다.</p>
        </div>
      )}

      {!isLoading && !isError && (data?.items.length ?? 0) > 0 && (
        <div className="krds-table-wrap">
          <table className="tbl col data">
            <caption>사용자 목록</caption>
            <colgroup>
              <col style={{ width: '25%' }} />
              <col style={{ width: '15%' }} />
              <col style={{ width: '15%' }} />
              <col style={{ width: '12%' }} />
              <col style={{ width: '18%' }} />
              <col />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">이메일</th>
                <th scope="col">이름</th>
                <th scope="col">역할</th>
                <th scope="col">활성</th>
                <th scope="col">가입일</th>
                <th scope="col">작업</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((u) => {
                const isSystem = u.id === SYSTEM_USER_ID
                const isSelf = u.id === currentUser?.id
                const isProtected = isSystem || isSelf

                return (
                  <tr key={u.id} style={{ opacity: u.is_active ? 1 : 0.6 }}>
                    <td style={{ fontWeight: 500 }}>
                      {u.email}
                      {isSystem && (
                        <span className="krds-badge xsmall bg-gray" style={{ marginLeft: 'var(--space-2)' }}>SYSTEM</span>
                      )}
                      {isSelf && (
                        <span className="krds-badge xsmall bg-primary" style={{ marginLeft: 'var(--space-2)' }}>나</span>
                      )}
                    </td>
                    <td style={{ color: 'var(--color-text-muted)' }}>{u.username}</td>
                    <td>
                      <select
                        value={u.role}
                        disabled={isProtected || updateUser.isPending}
                        onChange={(e) => handleRoleChange(u.id, e.target.value as 'viewer' | 'editor' | 'admin')}
                        className="krds-form-select small"
                      >
                        <option value="viewer">{ROLE_LABELS.viewer}</option>
                        <option value="editor">{ROLE_LABELS.editor}</option>
                        <option value="admin">{ROLE_LABELS.admin}</option>
                      </select>
                    </td>
                    <td>
                      <button
                        disabled={isProtected || updateUser.isPending}
                        onClick={() => handleToggleActive(u.id, !u.is_active)}
                        className={`krds-badge xsmall ${u.is_active ? 'bg-success' : 'bg-gray'}`}
                        style={{ border: 'none', cursor: isProtected ? 'not-allowed' : 'pointer' }}
                      >
                        {u.is_active ? '활성' : '비활성'}
                      </button>
                    </td>
                    <td style={{ color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>
                      {new Date(u.created_at).toLocaleDateString('ko-KR')}
                    </td>
                    <td>
                      {isProtected ? null : confirmDeleteId === u.id ? (
                        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                          <span style={{ fontSize: 12, color: '#dc2626' }}>삭제하시겠습니까?</span>
                          <button
                            onClick={() => handleDelete(u.id)}
                            disabled={deleteUser.isPending}
                            className="krds-btn xsmall primary"
                          >확인</button>
                          <button
                            onClick={() => setConfirmDeleteId(null)}
                            className="krds-btn xsmall secondary"
                          >취소</button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmDeleteId(u.id)}
                          className="krds-btn text xsmall icon-btn danger"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
