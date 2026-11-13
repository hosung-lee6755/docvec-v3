import { useState } from 'react'
import { ShieldOff, ShieldCheck, Trash2, UserPlus, X } from 'lucide-react'
import {
  useAddGroupMember, useCreateGroup, useDeleteGroup, useGroup, useGroups,
  useRemoveGroupMember, useUpdateGroup,
} from '../hooks/useAccess'
import type { Group } from '../hooks/useAccess'
import { useUsers } from '../hooks/useUsers'
import { useAuthStore } from '../store/authStore'
import { Alert, Badge, Button, EmptyState, ErrorAlert, Field, IconButton, Input, Page, PageBody, PageHeader, Select, SidePanel, Spinner, Split, Stat, StatStrip, Toolbar } from '../components/ui'

// v3 권한 모델 — 문서 접근 허용 목록(ACL)에 넣을 사용자 그룹을 관리한다(관리자 전용).
// 그룹을 지워도 문서 허용 목록의 해당 항목은 남는다(제한이 풀리지 않도록, fail-closed).

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
    <form onSubmit={handleSubmit} aria-label="새 그룹 만들기" style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', alignItems: 'flex-end' }}>
      <Field label="그룹 이름">
        {(id) => (
          <Input
            id={id} name="group_name" value={name} onChange={(e) => setName(e.target.value)}
            placeholder="예: 품질팀" maxLength={255} controlSize="sm"
          />
        )}
      </Field>
      <Field label="설명(선택)">
        {(id) => (
          <Input
            id={id} name="group_description" value={description} onChange={(e) => setDescription(e.target.value)}
            placeholder="설명" maxLength={2000} controlSize="sm"
          />
        )}
      </Field>
      <Button type="submit" variant="primary" size="sm" disabled={!name.trim() || createGroup.isPending}>
        그룹 추가
      </Button>
      {createGroup.isError && (
        <div style={{ flexBasis: '100%' }}>
          <ErrorAlert error={createGroup.error} message="그룹을 만들지 못했습니다." />
        </div>
      )}
    </form>
  )
}

function GroupDetailPanel({ groupId, onDeleted }: { groupId: string; onDeleted: () => void }) {
  const { data: group, isLoading, isError, error } = useGroup(groupId)
  const { data: users } = useUsers()
  const updateGroup = useUpdateGroup()
  const deleteGroup = useDeleteGroup()
  const addMember = useAddGroupMember()
  const removeMember = useRemoveGroupMember()
  const [candidate, setCandidate] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [draft, setDraft] = useState<{ name: string; description: string } | null>(null)

  if (isLoading) {
    return (
      <SidePanel title="그룹 상세" label="그룹 상세">
        <Spinner />
      </SidePanel>
    )
  }
  if (isError || !group) {
    return (
      <SidePanel title="그룹 상세" label="그룹 상세">
        <ErrorAlert error={error} message="그룹 정보를 불러오지 못했습니다." />
      </SidePanel>
    )
  }

  // AD에서 동기화되는 그룹은 이름과 구성원을 AD에서 바꾼다(서버도 409로 막는다)
  const isDirectory = group.source === 'ldap'
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
    <SidePanel
      eyebrow={isDirectory ? 'AD 동기화 그룹' : '그룹'}
      title={group.name}
      label="그룹 상세"
      actions={isDirectory ? undefined : (
        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          {draft ? null : (
            <Button variant="secondary" size="sm" onClick={() => setDraft({ name: group.name, description: group.description ?? '' })}>
              수정
            </Button>
          )}
          {confirmDelete ? (
            <>
              <Button variant="danger-solid" size="sm" disabled={deleteGroup.isPending} onClick={() => deleteGroup.mutate(group.id, { onSuccess: onDeleted })}>
                삭제 확인
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>취소</Button>
            </>
          ) : (
            <IconButton tone="danger" label="그룹 삭제" onClick={() => setConfirmDelete(true)}>
              <Trash2 size={14} aria-hidden="true" />
            </IconButton>
          )}
        </div>
      )}
    >
      {mutationError && <ErrorAlert error={mutationError.error} message="그룹 변경을 처리하지 못했습니다." />}

      {draft ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} maxLength={255} aria-label="그룹 이름" />
          <Input value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} maxLength={2000} aria-label="그룹 설명" placeholder="설명" />
          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <Button variant="primary" size="sm" onClick={handleSave} disabled={!draft.name.trim() || updateGroup.isPending}>저장</Button>
            <Button variant="ghost" size="sm" onClick={() => setDraft(null)}>취소</Button>
          </div>
        </div>
      ) : (
        <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>{group.description || '설명 없음'}</p>
      )}

      {isDirectory && (
        <Alert tone="info">사내 AD에서 동기화되는 그룹입니다. 이름과 구성원은 AD에서 바꾸면 다음 동기화 때 반영됩니다.</Alert>
      )}
      {confirmDelete && (
        <Alert tone="warning">그룹을 삭제해도 이 그룹을 허용 목록에 넣은 문서의 제한은 유지됩니다. 해당 문서는 문서 편집자가 허용 목록을 다시 정리해야 합니다.</Alert>
      )}

      {!isDirectory && (
        <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
          <Select
            controlSize="sm" value={candidate} onChange={(e) => setCandidate(e.target.value)}
            aria-label="추가할 사용자" style={{ flex: 1, minWidth: 0 }}
          >
            <option value="">추가할 사용자 선택</option>
            {candidates.map((u) => (
              <option key={u.id} value={u.id}>{u.username} ({u.email})</option>
            ))}
          </Select>
          <Button
            variant="primary" size="sm"
            icon={<UserPlus size={14} aria-hidden="true" />}
            disabled={!candidate || addMember.isPending}
            onClick={() => addMember.mutate({ groupId: group.id, userId: candidate }, { onSuccess: () => setCandidate('') })}
          >
            추가
          </Button>
        </div>
      )}

      {group.members.length === 0 ? (
        <p style={{ margin: 0, fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)' }}>멤버가 없습니다.</p>
      ) : (
        <div className="ds-table-wrap">
          <table className="ds-table ds-table--compact">
            <caption className="sr-only">{group.name} 멤버</caption>
            <thead>
              <tr>
                <th scope="col">이름</th>
                <th scope="col">추가일</th>
                <th scope="col"><span className="sr-only">작업</span></th>
              </tr>
            </thead>
            <tbody>
              {group.members.map((m) => (
                <tr key={m.user_id}>
                  <td>
                    <span style={{ fontWeight: 500 }}>{m.username}</span>
                    <span className="ds-cell-sub">{m.email}</span>
                  </td>
                  <td className="ds-cell-muted" style={{ whiteSpace: 'nowrap' }}>
                    {m.added_at ? new Date(m.added_at).toLocaleDateString('ko-KR') : '-'}
                  </td>
                  <td>
                    {!isDirectory && (
                      <IconButton
                        tone="danger"
                        label={`${m.username} 그룹에서 제거`}
                        disabled={removeMember.isPending}
                        onClick={() => removeMember.mutate({ groupId: group.id, userId: m.user_id })}
                      >
                        <X size={14} aria-hidden="true" />
                      </IconButton>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SidePanel>
  )
}

function GroupTable({ groups, selectedId, onSelect }: {
  groups: Group[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  if (groups.length === 0) {
    return <EmptyState icon={<ShieldCheck size={40} aria-hidden="true" />} title="아직 그룹이 없습니다." />
  }
  return (
    <div className="ds-table-wrap">
      <table className="ds-table">
        <caption className="sr-only">그룹 목록</caption>
        <thead>
          <tr>
            <th scope="col">그룹</th>
            <th scope="col" className="ds-cell-num">구성원</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => {
            const isSelected = g.id === selectedId
            const isEmpty = g.member_count === 0
            const rowClass = isSelected ? 'is-selected' : undefined
            return (
              <tr key={g.id} className={rowClass}>
                <td>
                  <button
                    type="button"
                    className="ds-link-btn"
                    aria-pressed={isSelected}
                    onClick={() => onSelect(g.id)}
                  >
                    {g.name}
                  </button>
                  {g.source === 'ldap' && <> <Badge tone="info" isPlain>AD</Badge></>}
                  {isEmpty && <span className="ds-cell-sub">구성원 없음</span>}
                </td>
                <td className="ds-cell-num">{g.member_count}명</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function GroupsPage() {
  const currentUser = useAuthStore((s) => s.user)
  const { data, isLoading, isError, error, refetch } = useGroups()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  if (currentUser?.role !== 'admin') {
    return (
      <Page>
        <EmptyState icon={<ShieldOff size={48} aria-hidden="true" />} title="관리자만 접근할 수 있습니다." />
      </Page>
    )
  }

  const groups = data?.items ?? []
  const directoryCount = groups.filter((g) => g.source === 'ldap').length
  const memberTotal = groups.reduce((sum, g) => sum + g.member_count, 0)
  const emptyCount = groups.filter((g) => g.member_count === 0).length

  return (
    <Page>
      <PageHeader
        title="그룹 관리"
        subtitle="문서의 접근 허용 목록에 넣을 사용자 그룹입니다. 구성원이 바뀌면 다음 검색·채팅부터 반영됩니다."
      />
      <StatStrip>
        <Stat label="그룹" value={groups.length} />
        <Stat label="AD 동기화 그룹" value={directoryCount} />
        <Stat label="구성원 합계" value={memberTotal} />
        <Stat label="구성원 없는 그룹" value={emptyCount} />
      </StatStrip>

      <Split
        main={(
          <PageBody>
            <CreateGroupForm />
            {isLoading && <Spinner />}
            {isError && <ErrorAlert error={error} message="그룹 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}
            {!isLoading && !isError && (
              <>
                <Toolbar label="그룹 목록 도구" meta={`${groups.length}개`}>
                  <span className="ds-cell-muted" style={{ fontSize: 'var(--text-sm)' }}>
                    그룹 이름을 누르면 오른쪽에 상세가 열립니다.
                  </span>
                </Toolbar>
                <GroupTable groups={groups} selectedId={selectedId} onSelect={setSelectedId} />
              </>
            )}
          </PageBody>
        )}
        panel={selectedId && !isLoading && !isError ? (
          <GroupDetailPanel key={selectedId} groupId={selectedId} onDeleted={() => setSelectedId(null)} />
        ) : undefined}
      />
    </Page>
  )
}
