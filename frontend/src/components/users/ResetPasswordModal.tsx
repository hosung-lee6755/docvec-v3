import { useResetPassword } from '../../hooks/useAccounts'
import type { User } from '../../hooks/useUsers'
import { Alert, Button, ErrorAlert, Modal } from '../ui'
import TemporaryPassword from './TemporaryPassword'

interface ResetPasswordModalProps {
  user: User | null
  onClose: () => void
}

/** 확인을 받은 뒤 임시 비밀번호를 새로 만들고, 그 사용자의 로그인과 외부 에이전트 토큰을 모두 끊는다 */
export default function ResetPasswordModal({ user, onClose }: ResetPasswordModalProps) {
  const resetPassword = useResetPassword()
  const temporary = resetPassword.data?.temporary_password

  const handleClose = () => {
    resetPassword.reset()
    onClose()
  }

  const footer = temporary ? (
    <Button variant="primary" onClick={handleClose}>전달했습니다, 닫기</Button>
  ) : (
    <>
      <Button variant="ghost" onClick={handleClose}>취소</Button>
      <Button
        variant="danger-solid"
        disabled={!user || resetPassword.isPending}
        onClick={() => user && resetPassword.mutate(user.id)}
      >
        {resetPassword.isPending ? '초기화 중...' : '초기화'}
      </Button>
    </>
  )

  return (
    <Modal isOpen={user !== null} title="비밀번호 초기화" onClose={handleClose} footer={footer} isDismissible={false}>
      {user && temporary ? (
        <TemporaryPassword email={user.email} password={temporary} />
      ) : (
        <div className="user-account-form">
          <p className="user-account-form__lead">{user?.email} 사용자의 비밀번호를 임시 비밀번호로 바꿉니다.</p>
          <Alert tone="warning">
            초기화하면 이 사용자는 지금 로그인한 모든 곳에서 로그아웃되고, 발급받은 외부 에이전트 토큰도 모두 회수됩니다.
            사용자는 임시 비밀번호로 로그인한 뒤 새 비밀번호를 정하고, 필요하면 토큰을 다시 발급받아야 합니다.
          </Alert>
          {resetPassword.isError && <ErrorAlert error={resetPassword.error} message="비밀번호를 초기화하지 못했습니다." />}
        </div>
      )}
    </Modal>
  )
}
