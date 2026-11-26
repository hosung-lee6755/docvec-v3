import { Loader2 } from 'lucide-react'
import type { DocumentTablesResult } from '../../hooks/useDocuments'
import { ErrorText } from '../ui'
import { SpanTable } from './SpanTable'

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
            {table.title && <strong style={{ marginLeft: 8, color: 'var(--color-text)' }}>{table.title}</strong>}
          </div>
          <SpanTable table={table} label={`표 ${i + 1}`} />
        </div>
      ))}
    </div>
  )
}
