import { useState } from 'react'
import { useCreateAccount } from '../../hooks/useAccounts'
import type { AccountRole, IssuedAccount } from '../../hooks/useAccounts'
import { SECURITY_LEVELS, SECURITY_LEVEL_LABELS } from '../../hooks/useAccess'
import type { SecurityLevel } from '../../hooks/useDocumentMetadata'
import { ROLE_LABELS } from '../../lib/roleLabels'
import { Button, ErrorAlert, Field, Input, Modal, Select } from '../ui'
import TemporaryPassword from './TemporaryPassword'

interface CreateAccountModalProps {
  isOpen: boolean
  onClose: () => void
}

const DEFAULT_CLEARANCE = ''

export default function CreateAccountModal({ isOpen, onClose }: CreateAccountModalProps) {
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [role, setRole] = useState<AccountRole>('viewer')
  const [clearance, setClearance] = useState<SecurityLevel | typeof DEFAULT_CLEARANCE>(DEFAULT_CLEARANCE)
  const [issued, setIssued] = useState<IssuedAccount | null>(null)
  const createAccount = useCreateAccount()

  const handleClose = () => {
    setEmail('')
    setUsername('')
    setRole('viewer')
    setClearance(DEFAULT_CLEARANCE)
    setIssued(null)
    createAccount.reset()
    onClose()
  }

  const handleSubmit = async () => {
    try {
      const result = await createAccount.mutateAsync({
        email: email.trim(),
        username: username.trim(),
        role,
        clearance_level: clearance || undefined,
      })
      setIssued(result)
    } catch {
      // 실패 원인은 폼 아래 알림이 보여 준다
    }
  }

  const footer = issued ? (
    <Button variant="primary" onClick={handleClose}>전달했습니다, 닫기</Button>
  ) : (
    <>
      <Button variant="ghost" onClick={handleClose}>취소</Button>
      <Button variant="primary" type="submit" form="create-account-form" disabled={createAccount.isPending}>
        {createAccount.isPending ? '만드는 중...' : '계정 만들기'}
      </Button>
    </>
  )

  return (
    <Modal
      isOpen={isOpen}
      title={issued ? '계정을 만들었습니다' : '계정 만들기'}
      onClose={handleClose}
      footer={footer}
      isDismissible={false}
    >
      {issued ? (
        <TemporaryPassword email={issued.user.email} password={issued.temporary_password} />
      ) : (
        <form
          id="create-account-form"
          className="user-account-form"
          onSubmit={(e) => {
            e.preventDefault()
            handleSubmit()
          }}
        >
          <p className="user-account-form__lead">
            임시 비밀번호를 만들어 드립니다. 사용자는 처음 로그인할 때 자기 비밀번호로 바꿉니다.
          </p>
          <Field label="이메일(로그인 아이디)">
            {(id) => (
              <Input id={id} type="text" inputMode="email" required value={email}
                onChange={(e) => setEmail(e.target.value)} placeholder="kim@example.com" />
            )}
          </Field>
          <Field label="이름">
            {(id) => (
              <Input id={id} value={username} onChange={(e) => setUsername(e.target.value)} placeholder="예: 김직원" />
            )}
          </Field>
          <Field label="역할">
            {(id) => (
              <Select id={id} value={role} onChange={(e) => setRole(e.target.value as AccountRole)}>
                <option value="viewer">{ROLE_LABELS.viewer}</option>
                <option value="editor">{ROLE_LABELS.editor}</option>
                <option value="admin">{ROLE_LABELS.admin}</option>
              </Select>
            )}
          </Field>
          <Field label="열람등급" hint="비워 두면 시스템 기본 열람등급을 씁니다.">
            {(id) => (
              <Select id={id} value={clearance} onChange={(e) => setClearance(e.target.value as SecurityLevel)}>
                <option value={DEFAULT_CLEARANCE}>기본값</option>
                {SECURITY_LEVELS.map((level) => (
                  <option key={level} value={level}>{SECURITY_LEVEL_LABELS[level]}</option>
                ))}
              </Select>
            )}
          </Field>
          {createAccount.isError && <ErrorAlert error={createAccount.error} message="계정을 만들지 못했습니다." />}
        </form>
      )}
    </Modal>
  )
}
