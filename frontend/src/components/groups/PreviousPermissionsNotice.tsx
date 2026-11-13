import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useDismissPreviousPermissions, useInheritPreviousPermissions, usePreviousPermissions,
} from '../../hooks/useAccess'
import { Alert, Button, ErrorAlert, Spinner } from '../ui'

// AD에서 같은 그룹이 지워졌다 새로 만들어지면 예전 그룹에 준 문서 권한이 아무에게도 걸리지 않은 채 남는다.
// 이름이 같아도 구성원이 다를 수 있어 자동으로 옮기지 않고, 관리자가 목록을 보고 정한다(app/services/group_carryover.py).

export default function PreviousPermissionsNotice({ groupId }: { groupId: string }) {
  const { data, isLoading, isError, error } = usePreviousPermissions(groupId, true)
  const inherit = useInheritPreviousPermissions()
  const dismiss = useDismissPreviousPermissions()
  const [confirmDismiss, setConfirmDismiss] = useState(false)

  if (isLoading) return <Spinner />
  if (isError) return <ErrorAlert error={error} message="예전 그룹의 권한을 불러오지 못했습니다." />
  if (!data?.previous_group_id) return null

  const failed = inherit.error ?? dismiss.error
  return (
    <section aria-label="예전 그룹 권한" className="group-carryover">
      <Alert tone="warning">
        AD에서 이 그룹이 지워졌다 다시 만들어졌습니다. 예전 그룹에 열어 둔 문서 {data.document_count}건은 지금 아무에게도
        열려 있지 않습니다. 구성원이 예전과 같다면 이어받고, 다르다면 이어받지 않고 문서 편집자가 다시 정하게 하세요.
        {data.connector_document_count > 0 && (
          <> 파일 서버에서 온 문서 {data.connector_document_count}건은 다음 원천 동기화 때 파일 권한대로 다시 걸립니다.</>
        )}
      </Alert>
      {data.documents.length > 0 && (
        <ul className="group-carryover__list">
          {data.documents.map((d) => (
            <li key={d.id}><Link to={`/documents/${d.id}`}>{d.title}</Link></li>
          ))}
          {data.document_count > data.documents.length && (
            <li className="ds-cell-muted">외 {data.document_count - data.documents.length}건</li>
          )}
        </ul>
      )}
      {failed && <ErrorAlert error={failed} message="처리하지 못했습니다." />}
      <div className="group-carryover__actions">
        <Button variant="primary" size="sm" disabled={inherit.isPending} onClick={() => inherit.mutate(groupId)}>
          문서 권한 이어받기
        </Button>
        {confirmDismiss ? (
          <>
            <Button variant="danger-solid" size="sm" disabled={dismiss.isPending} onClick={() => dismiss.mutate(groupId)}>
              이어받지 않기 확인
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmDismiss(false)}>취소</Button>
          </>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => setConfirmDismiss(true)}>이어받지 않기</Button>
        )}
      </div>
    </section>
  )
}
