import { useState } from 'react'
import { Loader2, ShieldOff, ShieldCheck, Trash2, UserPlus, X } from 'lucide-react'
import {
  useAddGroupMember, useCreateGroup, useDeleteGroup, useGroup, useGroups,
  useRemoveGroupMember, useUpdateGroup,
} from '../hooks/useAccess'
import type { Group } from '../hooks/useAccess'
import { useUsers } from '../hooks/useUsers'
import { useAuthStore } from '../store/authStore'

// v3 권한 모델 — 문서 접근 허용 목록(ACL)에 넣을 사용자 그룹을 관리한다(관리자 전용).
// 그룹을 지워도 문서 허용 목록의 해당 항목은 남는다(제한이 풀리지 않도록, fail-closed).

const ERROR_BOX: React.CSSProperties = {
  background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 'var(--radius-md)',
  padding: 'var(--space-3)', color: '#dc2626', fontSize: 13, marginBottom: 'var(--space-3)',
}

function errorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}

function CreateGroupForm() {
  const createGroup = useCreateGroup()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    createGroup.mutate(
      { name: name.trim(), description: description.trim() || null },
      { onSuccess: () => { setName(''); setDescription('') } },
    )
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', marginBottom: 'var(--space-4)' }}>
      <input
        id="group_name" name="group_name" value={name} onChange={(e) => setName(e.target.value)}
        placeholder="그룹 이름 (예: 품질팀)" maxLength={255} className="krds-input small" style={{ flex: '1 1 160px' }}
        aria-label="새 그룹 이름"
      />
      <input
        id="group_description" name="group_description" value={description}
        onChange={(e) => setDescription(e.target.value)} placeholder="설명 (선택)" maxLength={2000}
        className="krds-input small" style={{ flex: '2 1 220px' }} aria-label="새 그룹 설명"
      />
      <button type="submit" className="krds-btn small primary" disabled={!name.trim() || createGroup.isPending}>
        그룹 추가
      </button>
      {createGroup.isError && (
        <div style={{ ...ERROR_BOX, flexBasis: '100%', marginBottom: 0 }}>
          {errorMessage(createGroup.error, '그룹을 만들지 못했습니다.')}
        </div>
      )}
    </form>
  )
}

function GroupDetailPanel({ groupId, onDeleted }: { groupId: string; onDeleted: () => void }) {
  const { data: group, isLoading, isError } = useGroup(groupId)
  const { data: users } = useUsers()
  const updateGroup = useUpdateGroup()
  const deleteGroup = useDeleteGroup()
  const addMember = useAddGroupMember()
  const removeMember = useRemoveGroupMember()
  const [candidate, setCandidate] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [draft, setDraft] = useState<{ name: string; description: string } | null>(null)

  if (isLoading) return <Loader2 size={20} style={{ animation: 'spin 1s linear infinite' }} />
  if (isError || !group) return <div style={ERROR_BOX}>그룹 정보를 불러오지 못했습니다.</div>

  const memberIds = new Set(group.members.map((m) => m.user_id))
  const candidates = (users?.items ?? []).filter((u) => !memberIds.has(u.id) && u.is_active)
  const mutationError = [updateGroup, addMember, removeMember, deleteGroup].find((m) => m.isError)

  const handleSave = () => {
    if (!draft || !draft.name.trim()) return
    updateGroup.mutate(
      { id: group.id, name: draft.name.trim(), description: draft.description.trim() || null },
      { onSuccess: () => setDraft(null) },
    )
  }

  return (
    <div>
      {mutationError && <div style={ERROR_BOX}>{errorMessage(mutationError.error, '요청을 처리하지 못했습니다.')}</div>}

      {draft ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
          <input
            value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            className="krds-input small" maxLength={255} aria-label="그룹 이름"
          />
          <input
            value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            className="krds-input small" maxLength={2000} aria-label="그룹 설명" placeholder="설명"
          />
          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <button className="krds-btn xsmall primary" onClick={handleSave} disabled={!draft.name.trim() || updateGroup.isPending}>저장</button>
            <button className="krds-btn xsmall secondary" onClick={() => setDraft(null)}>취소</button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
          <div>
            <h2 style={{ fontSize: 18, fontWeight: 700 }}>{group.name}</h2>
            <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>{group.description || '설명 없음'}</p>
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-2)', flexShrink: 0 }}>
            <button
              className="krds-btn xsmall secondary"
              onClick={() => setDraft({ name: group.name, description: group.description ?? '' })}
            >수정</button>
            {confirmDelete ? (
              <>
                <button
                  className="krds-btn xsmall primary"
                  disabled={deleteGroup.isPending}
                  onClick={() => deleteGroup.mutate(group.id, { onSuccess: onDeleted })}
                >삭제 확인</button>
                <button className="krds-btn xsmall secondary" onClick={() => setConfirmDelete(false)}>취소</button>
              </>
            ) : (
              <button className="krds-btn text xsmall icon-btn danger" aria-label="그룹 삭제" onClick={() => setConfirmDelete(true)}>
                <Trash2 size={14} />
              </button>
            )}
          </div>
        </div>
      )}
      {confirmDelete && (
        <p style={{ fontSize: 12, color: '#b45309', marginBottom: 'var(--space-3)' }}>
          그룹을 삭제해도 이 그룹을 허용 목록에 넣은 문서의 제한은 유지됩니다. 해당 문서는 문서 편집자가 허용 목록을 다시 정리해야 합니다.
        </p>
      )}

      <div style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
        <select
          value={candidate} onChange={(e) => setCandidate(e.target.value)}
          className="krds-form-select small" style={{ flex: 1 }} aria-label="추가할 사용자"
        >
          <option value="">추가할 사용자 선택</option>
          {candidates.map((u) => (
            <option key={u.id} value={u.id}>{u.username} ({u.email})</option>
          ))}
        </select>
        <button
          className="krds-btn small primary"
          disabled={!candidate || addMember.isPending}
          onClick={() => addMember.mutate({ groupId: group.id, userId: candidate }, { onSuccess: () => setCandidate('') })}
        >
          <UserPlus size={14} /> 추가
        </button>
      </div>

      {group.members.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>멤버가 없습니다.</p>
      ) : (
        <div className="krds-table-wrap">
          <table className="tbl col data">
            <caption>{group.name} 멤버</caption>
            <thead>
              <tr>
                <th scope="col">이름</th>
                <th scope="col">이메일</th>
                <th scope="col">추가일</th>
                <th scope="col"><span className="sr-only">작업</span></th>
              </tr>
            </thead>
            <tbody>
              {group.members.map((m) => (
                <tr key={m.user_id}>
                  <td style={{ fontWeight: 500 }}>{m.username}</td>
                  <td style={{ color: 'var(--color-text-muted)' }}>{m.email}</td>
                  <td style={{ color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>
                    {m.added_at ? new Date(m.added_at).toLocaleDateString('ko-KR') : '-'}
                  </td>
                  <td>
                    <button
                      className="krds-btn text xsmall icon-btn danger"
                      aria-label={`${m.username} 그룹에서 제거`}
                      disabled={removeMember.isPending}
                      onClick={() => removeMember.mutate({ groupId: group.id, userId: m.user_id })}
                    >
                      <X size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function GroupList({ groups, selectedId, onSelect }: {
  groups: Group[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  if (groups.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 'var(--space-6)', color: 'var(--color-text-muted)' }}>
        <ShieldCheck size={40} style={{ margin: '0 auto var(--space-3)', display: 'block', opacity: 0.4 }} />
        <p>아직 그룹이 없습니다.</p>
      </div>
    )
  }
  return (
    <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {groups.map((g) => {
        const isSelected = g.id === selectedId
        return (
          <li key={g.id}>
            <button
              type="button"
              onClick={() => onSelect(g.id)}
              aria-pressed={isSelected}
              style={{
                width: '100%', textAlign: 'left', padding: 'var(--space-2) var(--space-3)',
                borderRadius: 'var(--radius-md)', cursor: 'pointer',
                border: `1px solid ${isSelected ? 'var(--color-primary, #256ef4)' : '#e2e8f0'}`,
                background: isSelected ? '#eff6ff' : 'transparent',
                display: 'flex', justifyContent: 'space-between', gap: 'var(--space-2)',
              }}
            >
              <span style={{ fontWeight: 600 }}>{g.name}</span>
              <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{g.member_count}명</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

export default function GroupsPage() {
  const currentUser = useAuthStore((s) => s.user)
  const { data, isLoading, isError } = useGroups()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  if (currentUser?.role !== 'admin') {
    return (
      <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
        <ShieldOff size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
        <p>관리자만 접근할 수 있습니다.</p>
      </div>
    )
  }

  const groups = data?.items ?? []

  return (
    <div>
      <style>{'@keyframes spin { to { transform: rotate(360deg) } }'}</style>
      <div style={{ marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>그룹 관리</h1>
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 4 }}>
          문서의 접근 허용 목록에 넣을 사용자 그룹입니다. 그룹 구성원이 바뀌면 다음 검색·채팅부터 바로 반영됩니다.
        </p>
      </div>

      <CreateGroupForm />

      {isLoading && <Loader2 size={24} style={{ animation: 'spin 1s linear infinite' }} />}
      {isError && <div style={ERROR_BOX}>그룹 목록을 불러오지 못했습니다.</div>}

      {!isLoading && !isError && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(200px, 280px) 1fr', gap: 'var(--space-6)', alignItems: 'start' }}>
          <GroupList groups={groups} selectedId={selectedId} onSelect={setSelectedId} />
          <section aria-label="그룹 상세">
            {selectedId ? (
              <GroupDetailPanel key={selectedId} groupId={selectedId} onDeleted={() => setSelectedId(null)} />
            ) : (
              <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>왼쪽에서 그룹을 선택하세요.</p>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
