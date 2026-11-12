import { useState } from 'react'
import { Loader2, PlayCircle } from 'lucide-react'
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
import { Alert, Badge, Button, Field, Input, Modal } from './ui'
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
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', alignItems: 'center', fontSize: 'var(--text-sm)' }}>
      <strong>{RUN_STATUS_LABELS[run.status]}</strong>
      <span style={{ color: 'var(--color-text-muted)' }}>· {RUN_TRIGGER_LABELS[run.trigger]} · top-K {run.top_k}</span>
      {isGoldenRunActive(run) && (
        <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-xs)' }}>(자동으로 갱신됩니다)</span>
      )}
      {run.status === 'FAILED' && run.error_message && <Alert tone="danger">{run.error_message}</Alert>}
    </div>
  )
}

function RunHistoryTable({
  runs, selectedRunId, onSelect, onSetBaseline, isBaselinePending,
}: {
  runs: GoldenEvalRun[]
  selectedRunId: string | undefined
  onSelect: (runId: string) => void
  onSetBaseline: (runId: string) => void
  isBaselinePending: boolean
}) {
  return (
    <div className="ds-table-wrap" style={{ maxHeight: 220, overflowY: 'auto' }}>
      <table className="ds-table ds-table--compact" aria-label="평가 실행 이력">
        <thead>
          <tr>
            <th scope="col">실행 시각</th>
            <th scope="col">상태</th>
            <th scope="col">실행 방식</th>
            <th scope="col">적중률</th>
            <th scope="col">표시</th>
            <th scope="col"><span className="sr-only">작업</span></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const rowClass = run.status === 'FAILED' ? 'is-danger' : run.is_regression ? 'is-warning' : undefined
            return (
              <tr key={run.id} className={rowClass} aria-selected={run.id === selectedRunId}>
                <td>{new Date(run.created_at).toLocaleString('ko-KR')}</td>
                <td>{RUN_STATUS_LABELS[run.status]}</td>
                <td className="ds-cell-muted">{RUN_TRIGGER_LABELS[run.trigger]}</td>
                <td className="ds-cell-num">{formatPercent(run.mean_hit_rate)}</td>
                <td>
                  <span style={{ display: 'inline-flex', gap: 'var(--space-1)' }}>
                    {run.is_baseline && <Badge tone="info">기준</Badge>}
                    {run.is_regression && <Badge tone="danger" hasDot>회귀</Badge>}
                  </span>
                </td>
                <td>
                  <span style={{ display: 'inline-flex', gap: 'var(--space-1)', justifyContent: 'flex-end' }}>
                    <Button size="sm" variant="ghost" onClick={() => onSelect(run.id)}>보기</Button>
                    {run.status === 'DONE' && !run.is_baseline && (
                      <Button size="sm" variant="ghost" onClick={() => onSetBaseline(run.id)} disabled={isBaselinePending}>
                        기준으로 삼기
                      </Button>
                    )}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
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
    <Modal
      isOpen
      size="lg"
      isDismissible={false}
      title={`골든 쿼리 평가 — ${collectionName}`}
      onClose={onClose}
      footer={<Button variant="secondary" onClick={onClose}>닫기</Button>}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
        <section style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)', margin: 0 }}>
            질문과 "이 질문에는 이 문서가 나와야 한다"는 기대 문서를 등록해두면, 검색 품질을
            정밀도·재현율·적중률·MRR로 측정할 수 있습니다. 기대 문서의 새 버전도 같은 문서로 칩니다.
          </p>

          <form
            onSubmit={handleAdd}
            style={{
              display: 'flex', flexDirection: 'column', gap: 'var(--space-2)',
              border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
            }}
          >
            <Input
              type="text"
              aria-label="새 골든 쿼리 질문"
              value={newQuery}
              onChange={(e) => setNewQuery(e.target.value)}
              placeholder="예: 에너지 절감 방안이 뭐야?"
            />
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>기대 문서 선택 (이 컬렉션 내)</div>
            <div style={{ maxHeight: 120, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
              {docOptions.map((d) => (
                <label key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 'var(--text-sm)' }}>
                  <input
                    type="checkbox"
                    id={`golden_expected_${d.id}`}
                    checked={newExpectedIds.has(d.id)}
                    onChange={() => toggleExpected(d.id)}
                  />
                  {d.name}
                </label>
              ))}
              {!docOptions.length && (
                <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>이 컬렉션에 문서가 없습니다.</span>
              )}
            </div>
            <div>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={createGoldenQuery.isPending || !newQuery.trim() || newExpectedIds.size === 0}
              >
                골든 쿼리 추가
              </Button>
            </div>
            {createGoldenQuery.isError && (
              <Alert tone="danger">{apiErrorDetail(createGoldenQuery.error, '골든 쿼리를 추가하지 못했습니다.')}</Alert>
            )}
          </form>
        </section>

        <section style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, margin: 0 }}>
            등록된 골든 쿼리 ({goldenData?.items.length ?? 0}개)
          </h3>
          <GoldenQueryList
            items={goldenData?.items ?? []}
            docOptions={docOptions}
            isSaving={updateGoldenQuery.isPending}
            saveError={updateGoldenQuery.isError ? apiErrorDetail(updateGoldenQuery.error, '수정하지 못했습니다.') : null}
            onSave={(queryId, input) => updateGoldenQuery.mutate({ queryId, ...input })}
            onDelete={(queryId) => deleteGoldenQuery.mutate(queryId)}
          />
        </section>

        <section style={{ borderTop: '1px solid var(--color-border)', paddingTop: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
            <Field label="top-K (비우면 컬렉션 설정 따름)">
              {(id) => (
                <Input
                  id={id}
                  type="number"
                  min={TOP_K_MIN}
                  max={TOP_K_MAX}
                  value={topKInput}
                  onChange={(e) => setTopKInput(e.target.value)}
                  controlSize="sm"
                  style={{ width: 96 }}
                  aria-invalid={!topK.isValid}
                />
              )}
            </Field>
            <Button
              variant="primary"
              onClick={handleRun}
              disabled={runEval.isPending || !goldenData?.items.length || !topK.isValid}
              icon={runEval.isPending
                ? <Loader2 size={14} aria-hidden="true" style={{ animation: 'spin 1s linear infinite' }} />
                : <PlayCircle size={14} aria-hidden="true" />}
            >
              평가 실행
            </Button>
          </div>
          {!topK.isValid && (
            <Alert tone="danger">top-K는 {TOP_K_MIN}에서 {TOP_K_MAX} 사이 정수여야 합니다.</Alert>
          )}
          {runEval.isError && (
            <Alert tone="danger">{apiErrorDetail(runEval.error, '평가를 시작하지 못했습니다.')}</Alert>
          )}
          {setBaseline.isError && (
            <Alert tone="danger">{apiErrorDetail(setBaseline.error, '기준으로 삼지 못했습니다.')}</Alert>
          )}

          {selectedRun && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              <RunStatusLine run={selectedRun} />
              <GoldenRunDetail run={selectedRun} filenameFor={filenameFor} />
            </div>
          )}

          {runs.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, margin: 0 }}>실행 이력</h3>
              <RunHistoryTable
                runs={runs}
                selectedRunId={selectedRun?.id}
                onSelect={setSelectedRunId}
                onSetBaseline={(runId) => setBaseline.mutate(runId)}
                isBaselinePending={setBaseline.isPending}
              />
            </div>
          )}
        </section>
      </div>
    </Modal>
  )
}
