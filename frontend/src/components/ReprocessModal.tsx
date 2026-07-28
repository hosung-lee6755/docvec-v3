import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2, X } from 'lucide-react'
import { useDocumentRuns, useReprocessImpact, useStartPartialReprocess } from '../hooks/useDocumentRuns'
import { useWorkflowRun } from '../hooks/useWorkflows'

const ENTRY_BLOCK_TYPE = 'file_validate'

interface ReprocessModalProps {
  documentId: string
  onClose: () => void
  onStarted?: (runId: string) => void
  initialBlockInstanceId?: string | null
}

export default function ReprocessModal({
  documentId, onClose, onStarted, initialBlockInstanceId,
}: ReprocessModalProps) {
  const { data: runsData } = useDocumentRuns(documentId)
  const latestRunId = runsData?.runs[0]?.id ?? null
  const { data: runDetail } = useWorkflowRun(latestRunId)
  // FAILED도 선택 가능해야 시간 제한 초과 등으로 멈춘 블록 자체를 다시 시작점으로
  // 고를 수 있다 — COMPLETED만 보여주면 정작 재시도하고 싶은 블록이 목록에서 빠진다.
  const steps = runDetail?.steps.filter((s) => (s.status === 'COMPLETED' || s.status === 'FAILED') && s.block_type) ?? []

  const [mode, setMode] = useState<'full' | 'specific'>(initialBlockInstanceId ? 'specific' : 'full')
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(initialBlockInstanceId ?? null)
  const [reason, setReason] = useState('')
  const [timeoutOverrideSeconds, setTimeoutOverrideSeconds] = useState('')
  const selectedStep = steps.find((s) => s.block_instance_id === selectedInstanceId) ?? null

  useEffect(() => {
    if (selectedInstanceId || steps.length === 0) return
    // 시간 제한 초과 등으로 멈춘 블록이 있으면, 사용자가 다시 시작하고 싶어할
    // 가능성이 가장 높은 지점이므로 모드와 무관하게 우선 선택해 둔다.
    const failedStep = steps.find((s) => s.status === 'FAILED')
    if (failedStep) {
      setMode('specific')
      setSelectedInstanceId(failedStep.block_instance_id)
      return
    }
    if (mode === 'specific') {
      setSelectedInstanceId(steps[0].block_instance_id)
    }
  }, [mode, selectedInstanceId, steps])

  const startBlockType = mode === 'full' ? ENTRY_BLOCK_TYPE : null
  const startBlockInstanceId = mode === 'specific' ? selectedInstanceId : null

  const { data: impact, isLoading: impactLoading, isError: impactError } = useReprocessImpact(
    documentId, startBlockType, startBlockInstanceId,
  )

  const startReprocess = useStartPartialReprocess()

  const canSubmit = mode === 'full' || !!selectedInstanceId
  const reusedLabels = steps
    .filter((s) => !impact?.affectedBlocks.includes(s.block_type as string))
    .map((s) => s.label ?? s.block_type)

  const overrideSeconds = Number.parseInt(timeoutOverrideSeconds, 10)
  const hasValidOverride = mode === 'specific' && !!selectedStep?.block_type && Number.isFinite(overrideSeconds) && overrideSeconds > 0

  const handleSubmit = async () => {
    if (!canSubmit) return
    const result = await startReprocess.mutateAsync({
      documentId,
      startBlockType: startBlockType ?? undefined,
      startBlockInstanceId: startBlockInstanceId ?? undefined,
      reason: reason.trim() || undefined,
      timeoutOverrides: hasValidOverride ? { [selectedStep!.block_type as string]: overrideSeconds } : undefined,
    })
    onStarted?.(result.run_id)
    onClose()
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
    }}>
      <section className="krds-modal fade shown in" role="dialog">
        <div className="modal-dialog modal-md">
          <div className="modal-content">
            <div className="modal-header">
              <h2 className="modal-title">문서 재처리</h2>
            </div>
            <div className="modal-conts">
              <div className="conts-area" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                <div className="form-group">
                  <div className="form-tit"><label>시작 지점</label></div>
                  <div className="form-conts" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                    <div style={{ display: 'inline-flex', gap: 4 }}>
                      <button
                        type="button"
                        onClick={() => setMode('full')}
                        aria-pressed={mode === 'full'}
                        className={mode === 'full' ? 'krds-btn primary small' : 'krds-btn secondary small'}
                        style={{ cursor: 'pointer' }}
                      >
                        전체 (파일 검증부터)
                      </button>
                      <button
                        type="button"
                        onClick={() => setMode('specific')}
                        aria-pressed={mode === 'specific'}
                        disabled={steps.length === 0}
                        className={mode === 'specific' ? 'krds-btn primary small' : 'krds-btn secondary small'}
                        style={{ cursor: steps.length === 0 ? 'not-allowed' : 'pointer' }}
                      >
                        특정 블록부터
                      </button>
                    </div>
                    {mode === 'specific' && (
                      <select
                        className="krds-form-select"
                        style={{ marginLeft: 'var(--space-5)' }}
                        value={selectedInstanceId ?? ''}
                        onChange={(e) => setSelectedInstanceId(e.target.value)}
                      >
                        {steps.map((s) => (
                          <option key={s.id} value={s.block_instance_id}>
                            {s.label ?? s.block_type}{s.status === 'FAILED' ? ' (실패)' : ''}
                          </option>
                        ))}
                      </select>
                    )}
                    {mode === 'specific' && selectedStep?.status === 'FAILED' && (
                      <div style={{
                        marginLeft: 'var(--space-5)', fontSize: 12, color: '#b91c1c',
                        display: 'flex', alignItems: 'center', gap: 'var(--space-1)',
                      }}>
                        <AlertTriangle size={13} /> {selectedStep.error_message ?? '실패 사유 정보 없음'}
                      </div>
                    )}
                    {mode === 'specific' && selectedStep && (
                      <div className="form-group" style={{ marginLeft: 'var(--space-5)', marginTop: 'var(--space-1)' }}>
                        <div className="form-tit"><label htmlFor="reprocess_timeout_override">시간 제한(초) 조정 (선택)</label></div>
                        <div className="form-conts">
                          <input
                            id="reprocess_timeout_override"
                            type="number"
                            min={1}
                            max={7200}
                            className="krds-input"
                            style={{ maxWidth: 160 }}
                            value={timeoutOverrideSeconds}
                            onChange={(e) => setTimeoutOverrideSeconds(e.target.value)}
                            placeholder="예: 1200"
                          />
                          <p style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 'var(--space-1)' }}>
                            비워두면 블록에 설정된 기본 시간 제한을 그대로 사용합니다. 이 재처리에만 적용되며,
                            워크플로우의 저장된 설정은 바뀌지 않습니다.
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                <div style={{
                  border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)',
                  padding: 'var(--space-3)', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)',
                }}>
                  <strong style={{ fontSize: 13 }}>영향 범위 미리보기</strong>
                  {impactLoading && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 12, color: 'var(--color-text-muted)' }}>
                      <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> 계산 중...
                    </div>
                  )}
                  {impactError && (
                    <div style={{ fontSize: 12, color: '#b91c1c' }}>영향 범위를 불러오지 못했습니다.</div>
                  )}
                  {impact && !impactLoading && (
                    <>
                      <div style={{ fontSize: 12, color: '#475569' }}>
                        <strong>재실행 블록:</strong> {impact.affectedBlocks.length > 0 ? impact.affectedBlocks.join(' → ') : '없음'}
                      </div>
                      {mode === 'specific' && reusedLabels.length > 0 && (
                        <div style={{ fontSize: 12, color: '#475569' }}>
                          <strong>캐시 재사용:</strong> {reusedLabels.join(', ')}
                        </div>
                      )}
                      <div style={{ fontSize: 12, color: '#475569', display: 'flex', gap: 'var(--space-4)' }}>
                        <span>영향 노드 수: {impact.affectedNodeCount}</span>
                        <span>영향 청크 수: {impact.affectedChunkCount}</span>
                      </div>
                      {impact.fullReprocessingRequired && (
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: 'var(--space-1)',
                          fontSize: 12, color: '#b45309',
                        }}>
                          <AlertTriangle size={13} /> 하위 사전/설정 변경으로 전체 재처리가 필요합니다.
                        </div>
                      )}
                    </>
                  )}
                </div>

                <div className="form-group">
                  <div className="form-tit"><label htmlFor="reprocess_reason">사유 (선택)</label></div>
                  <div className="form-conts">
                    <textarea
                      id="reprocess_reason"
                      className="krds-input"
                      rows={2}
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="재처리 사유를 입력하세요"
                    />
                  </div>
                </div>

                {startReprocess.isError && (
                  <div style={{ fontSize: 12, color: '#b91c1c' }}>재처리 시작에 실패했습니다.</div>
                )}

                <div className="modal-btn btn-wrap">
                  <button type="button" className="krds-btn medium secondary" onClick={onClose}>
                    취소
                  </button>
                  <button
                    type="button"
                    className="krds-btn medium primary"
                    onClick={handleSubmit}
                    disabled={!canSubmit || startReprocess.isPending || impactLoading}
                    style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}
                  >
                    {startReprocess.isPending && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                    재처리 시작
                  </button>
                </div>
              </div>
            </div>
            <button type="button" className="krds-btn medium icon btn-close close-modal" onClick={onClose}>
              <span className="sr-only">닫기</span>
              <X size={20} />
            </button>
          </div>
        </div>
        <div className="modal-back"></div>
      </section>
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
