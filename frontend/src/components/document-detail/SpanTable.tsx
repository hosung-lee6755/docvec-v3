import { layoutCells, type SpannedTable } from '../../lib/tableSpans'

// 합친 칸(spans)을 원본처럼 합쳐 그리는 표. 표 탭과 원문 대조가 함께 써서 같은 표가 어디서나 같은 모양으로 보인다
export function SpanTable({ table, label }: { table: SpannedTable; label?: string }) {
  return (
    <div style={{ overflowX: 'auto', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', margin: '4px 0 12px' }}>
      <table aria-label={label} style={{ borderCollapse: 'collapse', fontSize: 13, whiteSpace: 'nowrap' }}>
        <tbody>
          {layoutCells(table.rows, table.spans).map((row, ri) => (
            <tr key={ri}>
              {row.map((cell) => (
                <td
                  key={cell.column}
                  rowSpan={cell.rowSpan}
                  colSpan={cell.colSpan}
                  style={{
                    verticalAlign: 'top',
                    padding: '6px 10px',
                    border: '1px solid var(--color-border)',
                    background: ri === 0 ? 'var(--color-surface-subtle)' : undefined,
                    fontWeight: ri === 0 ? 600 : 400,
                  }}
                >
                  {cell.text}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
