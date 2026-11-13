import { Loader2 } from 'lucide-react'
import type { DocumentTablesResult } from '../../hooks/useDocuments'
import { ErrorText } from '../ui'

interface TablesTabProps {
  isLoading: boolean
  isError: boolean
  error?: unknown
  tablesResult: DocumentTablesResult | undefined
  isPdfDoc: boolean
}

export default function TablesTab({
  isLoading,
  isError,
  error,
  tablesResult,
  isPdfDoc,
}: TablesTabProps) {
  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-6)' }}>
        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
      </div>
    )
  }

  if (isError) {
    return (
      <ErrorText error={error} message="표 데이터를 불러오지 못했습니다." />
    )
  }

  if (!tablesResult?.tables.length) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: 0 }}>
        추출된 표가 없습니다.
      </p>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
      {tablesResult.tables.map((table, i) => (
        <div key={i}>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 'var(--space-2)' }}>
            표 {i + 1}{isPdfDoc ? ` · ${table.page_number}쪽` : ''}
          </div>
          <div style={{ overflowX: 'auto', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)' }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 13, whiteSpace: 'nowrap' }}>
              <tbody>
                {table.rows.map((row, ri) => (
                  <tr key={ri}>
                    {row.map((cell, ci) => (
                      <td
                        key={ci}
                        style={{
                          padding: '6px 10px',
                          border: '1px solid var(--color-border)',
                          background: ri === 0 ? 'var(--color-surface-subtle)' : undefined,
                          fontWeight: ri === 0 ? 600 : 400,
                        }}
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  )
}
