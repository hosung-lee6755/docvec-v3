import { useState } from 'react'
import { X, Loader2, PlayCircle } from 'lucide-react'
import {
  useGoldenQueries,
  useCreateGoldenQuery,
  useDeleteGoldenQuery,
  useUpdateGoldenQuery,
  useGoldenEvalRuns,
  useRunGoldenEval,
  useSetGoldenBaseline,
  isGoldenRunActive,
  type GoldenEvalRun,
} from '../hooks/useGoldenQueries'
import { useDocuments } from '../hooks/useDocuments'
import { apiErrorDetail } from '../lib/apiError'
import GoldenRunDetail from './golden/GoldenRunDetail'
import GoldenQueryList from './golden/GoldenQueryList'
import { RUN_STATUS_LABELS, RUN_TRIGGER_LABELS, formatPercent } from './golden/goldenLabels'

interface GoldenEvalModalProps {
  collectionId: string
  collectionName: string
  onClose: () => void
}

// 백엔드 GoldenEvalRunCreate의 top_k 범위와 맞춘다.
const TOP_K_MIN = 1
const TOP_K_MAX = 20

function parseTopK(input: string): { value: number | null; isValid: boolean } {
  const trimmed = input.trim()
  if (trimmed === '') return { value: null, isValid: true }
  const value = Number(trimmed)
  const isValid = Number.isInteger(value) && value >= TOP_K_MIN && value <= TOP_K_MAX
  return { value: isValid ? value : null, isValid }
}

function RunStatusLine({ run }: { run: GoldenEvalRun }) {
  return (
    <div style={{ fontSize: 13, display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', alignItems: 'center' }}>
      <strong>{RUN_STATUS_LABELS[run.status]}</strong>
      <span style={{ color: 'var(--color-text-muted)' }}>· {RUN_TRIGGER_LABELS[run.trigger]} · top-K {run.top_k}</span>
      {isGoldenRunActive(run) && <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>(자동으로 갱신됩니다)</span>}
      {run.status === 'FAILED' && run.error_message && (
        <span role="alert" style={{ color: '#dc2626', fontSize: 12 }}>{run.error_message}</span>
      )}
    </div>
  )
}

export default function GoldenEvalModal({ collectionId, collectionName, onClose }: GoldenEvalModalProps) {
  const { data: goldenData } = useGoldenQueries(collectionId)
  const createGoldenQuery = useCreateGoldenQuery(collectionId)
  const deleteGoldenQuery = useDeleteGoldenQuery(collectionId)
  const updateGoldenQuery = useUpdateGoldenQuery(collectionId)
  const { data: runsData } = useGoldenEvalRuns(collectionId)
  const runEval = useRunGoldenEval(collectionId)
  const setBaseline = useSetGoldenBaseline(collectionId)
  const { data: docsData } = useDocuments({ collectionId, limit: 100 })
  // 기대 문서가 새 버전으로 바뀌어 이전 버전을 가리켜도 이름이 보이도록 모든 버전에서 찾는다
  const { data: allVersionsData } = useDocuments({ collectionId, limit: 200, lifecycle: 'all' })

  const [newQuery, setNewQuery] = useState('')
  const [newExpectedIds, setNewExpectedIds] = useState<Set<string>>(new Set())
  // 비워 두면 컬렉션의 검색 설정 top-k를 따른다.
  const [topKInput, setTopKInput] = useState('')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  const runs = runsData?.items ?? []
  const latestRun = runs[0] ?? null
  const selectedRun = runs.find((r) => r.id === selectedRunId) ?? latestRun
  const topK = parseTopK(topKInput)
  const docOptions = (docsData?.items ?? []).map((d) => ({ id: d.id, name: d.original_filename }))

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

  const filenameFor = (docId: string) => {
    const doc = allVersionsData?.items.find((d) => d.id === docId)
      ?? docsData?.items.find((d) => d.id === docId)
    if (!doc) return docId.slice(0, 8)
    return doc.lifecycle_state === 'superseded'
      ? `${doc.original_filename} (v${doc.version_number}, 이전 버전)`
      : doc.original_filename
  }

  const handleRun = () => {
    if (!topK.isValid) return
    runEval.mutate(topK.value)
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 60,
    }}>
      <section className="krds-modal fade shown in" role="dialog" aria-label={`골든 쿼리 평가 — ${collectionName}`}>
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
                    정밀도·재현율·적중률·MRR로 측정할 수 있습니다. 기대 문서의 새 버전도 같은 문서로 칩니다.
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
                      {docOptions.map((d) => (
                        <div key={d.id} className="krds-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <input
                            type="checkbox"
                            id={`golden_expected_${d.id}`}
                            checked={newExpectedIds.has(d.id)}
                            onChange={() => toggleExpected(d.id)}
                          />
                          <label htmlFor={`golden_expected_${d.id}`} style={{ fontSize: 12 }}>{d.name}</label>
                        </div>
                      ))}
                      {!docOptions.length && (
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
                    {createGoldenQuery.isError && (
                      <p role="alert" style={{ color: '#dc2626', fontSize: 12, margin: 0 }}>
                        {apiErrorDetail(createGoldenQuery.error, '골든 쿼리를 추가하지 못했습니다.')}
                      </p>
                    )}
                  </form>
                </div>

                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 'var(--space-2)' }}>
                    등록된 골든 쿼리 ({goldenData?.items.length ?? 0}개)
                  </div>
                  <GoldenQueryList
                    items={goldenData?.items ?? []}
                    docOptions={docOptions}
                    isSaving={updateGoldenQuery.isPending}
                    saveError={updateGoldenQuery.isError ? apiErrorDetail(updateGoldenQuery.error, '수정하지 못했습니다.') : null}
                    onSave={(queryId, input) => updateGoldenQuery.mutate({ queryId, ...input })}
                    onDelete={(queryId) => deleteGoldenQuery.mutate(queryId)}
                  />
                </div>

                <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                    <label htmlFor="golden_top_k" style={{ fontSize: 12 }}>top-K (비우면 컬렉션 설정 따름)</label>
                    <input
                      id="golden_top_k"
                      type="number" min={TOP_K_MIN} max={TOP_K_MAX} value={topKInput}
                      onChange={(e) => setTopKInput(e.target.value)}
                      className="krds-input" style={{ width: 80 }}
                      aria-invalid={!topK.isValid}
                    />
                    <button
                      type="button"
                      onClick={handleRun}
                      disabled={runEval.isPending || !goldenData?.items.length || !topK.isValid}
                      className="krds-btn small primary"
                      style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                    >
                      {runEval.isPending ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <PlayCircle size={14} />}
                      평가 실행
                    </button>
                  </div>
                  {!topK.isValid && (
                    <p role="alert" style={{ color: '#dc2626', fontSize: 12, margin: 0 }}>top-K는 {TOP_K_MIN}에서 {TOP_K_MAX} 사이 정수여야 합니다.</p>
                  )}
                  {runEval.isError && (
                    <p role="alert" style={{ color: '#dc2626', fontSize: 12, margin: 0 }}>
                      {apiErrorDetail(runEval.error, '평가를 시작하지 못했습니다.')}
                    </p>
                  )}
                  {setBaseline.isError && (
                    <p role="alert" style={{ color: '#dc2626', fontSize: 12, margin: 0 }}>
                      {apiErrorDetail(setBaseline.error, '기준으로 삼지 못했습니다.')}
                    </p>
                  )}

                  {selectedRun && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                      <RunStatusLine run={selectedRun} />
                      <GoldenRunDetail run={selectedRun} filenameFor={filenameFor} />
                    </div>
                  )}

                  {runs.length > 0 && (
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 'var(--space-1)' }}>실행 이력</div>
                      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
                        {runs.map((run) => (
                          <li key={run.id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap', fontSize: 12, padding: 'var(--space-1) var(--space-2)', background: run.id === selectedRun?.id ? '#eff6ff' : '#f8fafc', borderRadius: 'var(--radius-sm)' }}>
                            <span>{new Date(run.created_at).toLocaleString('ko-KR')}</span>
                            <span>{RUN_STATUS_LABELS[run.status]}</span>
                            <span style={{ color: 'var(--color-text-muted)' }}>{RUN_TRIGGER_LABELS[run.trigger]}</span>
                            <span>적중률 {formatPercent(run.mean_hit_rate)}</span>
                            {run.is_baseline && <span className="krds-badge xsmall bg-information">기준</span>}
                            {run.is_regression && <span className="krds-badge xsmall bg-danger">회귀</span>}
                            <button type="button" onClick={() => setSelectedRunId(run.id)} className="krds-btn text xsmall">보기</button>
                            {run.status === 'DONE' && !run.is_baseline && (
                              <button
                                type="button"
                                onClick={() => setBaseline.mutate(run.id)}
                                disabled={setBaseline.isPending}
                                className="krds-btn text xsmall"
                              >
                                기준으로 삼기
                              </button>
                            )}
                          </li>
                        ))}
                      </ul>
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
