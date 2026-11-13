import type { ImportedAccount } from '../hooks/useAccounts'

const BOM = '﻿'

/** 엑셀에서 한글이 깨지지 않게 BOM을 붙인 일괄 등록 양식 */
export const ACCOUNT_CSV_TEMPLATE =
  `${BOM}이메일,이름,역할,열람등급,그룹\n`
  + 'kim@example.com,김직원,viewer,Internal,영업팀;기획팀\n'
  + 'lee@example.com,이직원,editor,,\n'

function csvCell(value: string): string {
  return /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value
}

/** 발급 결과(임시 비밀번호 포함)를 직원에게 나눠 줄 CSV로 만든다 */
export function issuedAccountsCsv(items: ImportedAccount[]): string {
  const rows = items.map((a) =>
    [a.email, a.username, a.role, a.groups.join(';'), a.temporary_password].map(csvCell).join(','),
  )
  return `${BOM}이메일,이름,역할,그룹,임시 비밀번호\n${rows.join('\n')}\n`
}

export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
