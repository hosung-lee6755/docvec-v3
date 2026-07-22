import { useState } from 'react'
import { X, Trash2, Loader2, PlayCircle } from 'lucide-react'
import {
  useGoldenQueries,
  useCreateGoldenQuery,
  useDeleteGoldenQuery,
  useGoldenEvalRuns,
  useRunGoldenEval,
} from '../hooks/useGoldenQueries'
import { useDocuments } from '../hooks/useDocuments'

interface GoldenEvalModalProps {
  collectionId: string
  collectionName: string
  onClose: () => void
}

export default function GoldenEvalModal({ collectionId, collectionName, onClose }: GoldenEvalModalProps) {
  const { data: goldenData } = useGoldenQueries(collectionId)
  const createGoldenQuery = useCreateGoldenQuery(collectionId)
  const deleteGoldenQuery = useDeleteGoldenQuery(collectionId)
  const { data: runsData } = useGoldenEvalRuns(collectionId)
  const runEval = useRunGoldenEval(collectionId)
  const { data: docsData } = useDocuments({ collectionId, limit: 100 })

  const [newQuery, setNewQuery] = useState('')
  const [newExpectedIds, setNewExpectedIds] = useState<Set<string>>(new Set())
  const [topK, setTopK] = useState(5)

  const latestRun = runsData?.items[0]

  const toggleExpected = (docId: string) =>
    setNewExpectedIds((prev) => {
      const next = new Set(prev)
      next.has(docId) ? next.delete(docId) : next.add(docId)
      return next
    })

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newQuery.trim() || newExpectedIds.size === 0) return
    await createGoldenQuery.mutateAsync({
      query: newQuery.trim(),
      expected_document_ids: Array.from(newExpectedIds),
    })
    setNewQuery('')
    setNewExpectedIds(new Set())
  }

  const filenameFor = (docId: string) =>
    docsData?.items.find((d) => d.id === docId)?.original_filename ?? docId.slice(0, 8)

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60,
    }}>
      <section className="krds-modal fade shown in" role="dialog">
        <div className="modal-dialog modal-md">
          <div className="modal-content">
            <div className="modal-header">
              <h2 className="modal-title">골든 쿼리 평가 — {collectionName}</h2>
            </div>
            <div className="modal-conts">
              <div className="conts-area" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>

                <div>
                  <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 'var(--space-2)' }}>
                    질문과 "이 질문에는 이 문서가 나와야 한다"는 기대 문서를 등록해두면, 검색 품질을
                    정밀도(precision)·재현율(recall)로 측정할 수 있습니다.
                  </p>

                  <form onSubmit={handleAdd} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)' }}>
                    <input
                      type="text"
                      value={newQuery}
                      onChange={(e) => setNewQuery(e.target.value)}
                      placeholder="예: 에너지 절감 방안이 뭐야?"
                      className="krds-input"
                      style={{ width: '100%' }}
                    />
                    <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>기대 문서 선택 (이 컬렉션 내)</div>
                    <div style={{ maxHeight: 120, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
                      {docsData?.items.map((d) => (
                        <div key={d.id} className="krds-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <input
                            type="checkbox"
                            id={`golden_expected_${d.id}`}
                            checked={newExpectedIds.has(d.id)}
                            onChange={() => toggleExpected(d.id)}
                          />
                          <label htmlFor={`golden_expected_${d.id}`} style={{ fontSize: 12 }}>{d.original_filename}</label>
                        </div>
                      ))}
                      {!docsData?.items.length && (
                        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>이 컬렉션에 문서가 없습니다.</span>
                      )}
                    </div>
                    <button
                      type="submit"
                      disabled={createGoldenQuery.isPending || !newQuery.trim() || newExpectedIds.size === 0}
                      className="krds-btn small primary"
                      style={{ alignSelf: 'flex-start' }}
                    >
                      골든 쿼리 추가
                    </button>
                  </form>
                </div>

                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 'var(--space-2)' }}>
                    등록된 골든 쿼리 ({goldenData?.items.length ?? 0}개)
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 140, overflowY: 'auto' }}>
                    {goldenData?.items.map((gq) => (
                      <div key={gq.id} style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        fontSize: 12, padding: 'var(--space-1) var(--space-2)', background: '#f8fafc', borderRadius: 'var(--radius-sm)',
                      }}>
                        <span>
                          {gq.query} <span style={{ color: 'var(--color-text-muted)' }}>({gq.expected_document_ids.length}개 문서)</span>
                        </span>
                        <button
                          type="button"
                          onClick={() => deleteGoldenQuery.mutate(gq.id)}
                          className="krds-btn text xsmall"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 'var(--space-4)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-3)' }}>
                    <label style={{ fontSize: 12 }}>top-K</label>
                    <input
                      type="number" min={1} max={50} value={topK}
                      onChange={(e) => setTopK(Number(e.target.value))}
                      className="krds-input" style={{ width: 60 }}
                    />
                    <button
                      type="button"
                      onClick={() => runEval.mutate(topK)}
                      disabled={runEval.isPending || !goldenData?.items.length}
                      className="krds-btn small primary"
                      style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                    >
                      {runEval.isPending ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <PlayCircle size={14} />}
                      평가 실행
                    </button>
                  </div>

                  {latestRun && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                      <div style={{ display: 'flex', gap: 'var(--space-4)', fontSize: 13 }}>
                        <span>평균 정밀도(Precision): <strong>{(latestRun.mean_precision * 100).toFixed(1)}%</strong></span>
                        <span>평균 재현율(Recall): <strong>{(latestRun.mean_recall * 100).toFixed(1)}%</strong></span>
                      </div>
                      <div style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)' }}>
                        <table className="krds-table" style={{ width: '100%', fontSize: 12 }}>
                          <thead>
                            <tr><th>질문</th><th>Precision</th><th>Recall</th><th>기대/조회 문서</th></tr>
                          </thead>
                          <tbody>
                            {latestRun.results.map((r) => (
                              <tr key={r.golden_query_id}>
                                <td>{r.query}</td>
                                <td>{(r.precision * 100).toFixed(0)}%</td>
                                <td>{(r.recall * 100).toFixed(0)}%</td>
                                <td style={{ color: 'var(--color-text-muted)' }}>
                                  기대: {r.expected_document_ids.map(filenameFor).join(', ')}
                                  <br />조회: {r.retrieved_document_ids.map(filenameFor).join(', ') || '—'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
            <div className="modal-btn btn-wrap">
              <button type="button" onClick={onClose} className="krds-btn medium secondary">닫기</button>
            </div>
            <button type="button" onClick={onClose} className="krds-btn medium icon btn-close">
              <span className="sr-only">닫기</span>
              <X size={20} />
            </button>
          </div>
        </div>
        <div className="modal-back"></div>
      </section>
    </div>
  )
}
