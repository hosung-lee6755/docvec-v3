import { useState } from 'react'
import { Download, Upload } from 'lucide-react'
import { importProblems, useImportAccounts } from '../../hooks/useAccounts'
import type { ImportResult } from '../../hooks/useAccounts'
import { ACCOUNT_CSV_TEMPLATE, downloadText, issuedAccountsCsv } from '../../lib/accountCsv'
import { Alert, Button, ErrorAlert, Modal } from '../ui'

interface ImportAccountsModalProps {
  isOpen: boolean
  onClose: () => void
}

function ImportResultTable({ result }: { result: ImportResult }) {
  return (
    <div className="user-account-import">
      <Alert tone="warning">
        임시 비밀번호는 지금 한 번만 보입니다. 결과 CSV를 받아 각 직원에게 따로 전달한 뒤, 파일은 안전하게 지우세요.
      </Alert>
      <div className="ds-table-wrap">
        <table className="ds-table">
          <caption className="sr-only">발급한 계정</caption>
          <thead>
            <tr>
              <th scope="col">이메일</th>
              <th scope="col">이름</th>
              <th scope="col">그룹</th>
              <th scope="col">임시 비밀번호</th>
            </tr>
          </thead>
          <tbody>
            {result.created.map((a) => (
              <tr key={a.email}>
                <td>{a.email}</td>
                <td className="ds-cell-muted">{a.username}</td>
                <td className="ds-cell-muted">{a.groups.join(', ') || '-'}</td>
                <td><code>{a.temporary_password}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function ImportAccountsModal({ isOpen, onClose }: ImportAccountsModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const importAccounts = useImportAccounts()
  const problems = importProblems(importAccounts.error)

  const handleClose = () => {
    setFile(null)
    setResult(null)
    importAccounts.reset()
    onClose()
  }

  const handleUpload = async () => {
    if (!file) return
    try {
      setResult(await importAccounts.mutateAsync(file))
    } catch {
      // 줄별 문제나 실패 원인은 아래에 보여 준다
    }
  }

  const footer = result ? (
    <>
      <Button
        variant="secondary"
        icon={<Download size={14} />}
        onClick={() => downloadText('발급_계정_임시비밀번호.csv', issuedAccountsCsv(result.created))}
      >
        결과 CSV 받기
      </Button>
      <Button variant="primary" onClick={handleClose}>닫기</Button>
    </>
  ) : (
    <>
      <Button variant="ghost" onClick={handleClose}>취소</Button>
      <Button variant="primary" icon={<Upload size={14} />} disabled={!file || importAccounts.isPending} onClick={handleUpload}>
        {importAccounts.isPending ? '등록 중...' : '등록'}
      </Button>
    </>
  )

  return (
    <Modal
      isOpen={isOpen}
      size="lg"
      title={result ? `${result.count}개 계정을 만들었습니다` : 'CSV로 일괄 등록'}
      onClose={handleClose}
      footer={footer}
      isDismissible={false}
    >
      {result ? (
        <ImportResultTable result={result} />
      ) : (
        <div className="user-account-import">
          <ol className="user-account-import__steps">
            <li>
              양식을 받아 한 줄에 한 명씩 채웁니다. 이메일만 꼭 넣으면 되고, 역할을 비우면 열람자가 됩니다.
              그룹은 세미콜론(;)으로 여러 개를 적을 수 있으며, 그룹 화면에서 먼저 만든 그룹만 쓸 수 있습니다.
              <div className="user-account-import__template">
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Download size={12} />}
                  onClick={() => downloadText('계정_일괄등록_양식.csv', ACCOUNT_CSV_TEMPLATE)}
                >
                  양식 받기
                </Button>
              </div>
            </li>
            <li>엑셀에서 저장할 때는 &apos;CSV UTF-8&apos; 형식을 고릅니다. 한 번에 500명까지 올릴 수 있습니다.</li>
            <li>고칠 줄이 하나라도 있으면 아무 계정도 만들지 않고, 고칠 줄을 알려 드립니다.</li>
          </ol>
          <label className="user-account-import__file">
            <span className="ds-field__label">CSV 파일</span>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                importAccounts.reset()
              }}
            />
          </label>
          {problems.length > 0 ? (
            <Alert tone="danger">
              <p>고칠 줄이 있어 아무 계정도 만들지 않았습니다. 아래 줄을 고쳐 다시 올리세요.</p>
              <ul className="user-account-import__problems">
                {problems.map((p) => (
                  <li key={`${p.line}-${p.message}`}>{p.line}번째 줄: {p.message}</li>
                ))}
              </ul>
            </Alert>
          ) : (
            importAccounts.isError && <ErrorAlert error={importAccounts.error} message="계정을 등록하지 못했습니다." />
          )}
        </div>
      )}
    </Modal>
  )
}
