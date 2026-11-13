import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useDocumentRuns, useReprocessImpact, useStartPartialReprocess } from '../hooks/useDocumentRuns'
import { useWorkflowRun } from '../hooks/useWorkflows'
import { Alert, Button, Card, ErrorAlert, ErrorText, Field, Input, Modal, Select, Spinner, Textarea } from './ui'
import { explainFailure } from '../lib/apiError'
import '../styles/screens/documents.css'

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
  const steps = useMemo(
    () => runDetail?.steps.filter((s) => (s.status === 'COMPLETED' || s.status === 'FAILED') && s.block_type) ?? [],
    [runDetail],
  )

  const [mode, setMode] = useState<'full' | 'specific'>(initialBlockInstanceId ? 'specific' : 'full')
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(initialBlockInstanceId ?? null)
  const [reason, setReason] = useState('')
  // 워크플로우 설정(예: 텍스트 추출 엔진)을 바꿔 새 버전을 게시한 뒤 반영하려면 켠다.
  // 끄면 이 문서를 처리했던 버전 그대로 재실행한다.
  const [useLatestVersion, setUseLatestVersion] = useState(false)
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

  const latestVersionApplies = mode === 'full' && useLatestVersion
  const startBlockType = mode === 'full' ? ENTRY_BLOCK_TYPE : null
  const startBlockInstanceId = mode === 'specific' ? selectedInstanceId : null

  const { data: impact, isLoading: impactLoading, isError: impactError, error: impactErrorObj } = useReprocessImpact(
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
    const timeoutOverrides = hasValidOverride && selectedStep?.block_type
      ? { [selectedStep.block_type as string]: overrideSeconds }
      : undefined
    const result = await startReprocess.mutateAsync({
      documentId,
      startBlockType: startBlockType ?? undefined,
      startBlockInstanceId: startBlockInstanceId ?? undefined,
      reason: reason.trim() || undefined,
      timeoutOverrides,
      useLatestVersion: latestVersionApplies,
    })
    onStarted?.(result.run_id)
    onClose()
  }

  const footer = (
    <>
      <Button variant="secondary" onClick={onClose}>취소</Button>
      <Button
        variant="primary"
        onClick={handleSubmit}
        disabled={!canSubmit || startReprocess.isPending || impactLoading}
        icon={startReprocess.isPending ? <Spinner size={14} /> : undefined}
      >
        재처리 시작
      </Button>
    </>
  )

  return (
    <Modal isOpen title="문서 재처리" onClose={onClose} footer={footer} size="lg">
      <div className="documents-stack">
        <div role="group" aria-label="시작 지점" className="documents-stack">
          <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
            <Button
              size="sm"
              variant={mode === 'full' ? 'primary' : 'secondary'}
              aria-pressed={mode === 'full'}
              onClick={() => setMode('full')}
            >
              전체 (파일 검증부터)
            </Button>
            <Button
              size="sm"
              variant={mode === 'specific' ? 'primary' : 'secondary'}
              aria-pressed={mode === 'specific'}
              disabled={steps.length === 0}
              onClick={() => setMode('specific')}
            >
              특정 블록부터
            </Button>
          </div>

          {mode === 'full' && (
            <div className="documents-stack" style={{ gap: 'var(--space-1)' }}>
              <label className="documents-check">
                <input
                  type="checkbox"
                  checked={useLatestVersion}
                  onChange={(e) => setUseLatestVersion(e.target.checked)}
                />
                <span>최신 게시 버전으로 처리</span>
              </label>
              <p className="documents-note">
                워크플로우를 수정해 새 버전을 게시했다면 켜세요(예: 텍스트 추출 엔진 변경).
                끄면 이 문서를 처리했던 버전 그대로 다시 실행하므로 변경한 설정이 반영되지 않습니다.
              </p>
            </div>
          )}

          {mode === 'specific' && (
            <Field label="재시작할 블록">
              {(id) => (
                <Select
                  id={id}
                  controlSize="sm"
                  value={selectedInstanceId ?? ''}
                  onChange={(e) => setSelectedInstanceId(e.target.value)}
                >
                  {steps.map((s) => (
                    <option key={s.id} value={s.block_instance_id}>
                      {s.label ?? s.block_type}{s.status === 'FAILED' ? ' (실패)' : ''}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}

          {mode === 'specific' && selectedStep?.status === 'FAILED' && (
            <Alert tone="danger">
              <AlertTriangle size={13} aria-hidden="true" /> {explainFailure(selectedStep.error_message)}
            </Alert>
          )}

          {mode === 'specific' && selectedStep && (
            <Field
              label="시간 제한(초) 조정 (선택)"
              hint="비워두면 블록에 설정된 기본 시간 제한을 그대로 사용합니다. 이 재처리에만 적용되며, 워크플로우의 저장된 설정은 바뀌지 않습니다."
            >
              {(id) => (
                <Input
                  id={id}
                  type="number"
                  min={1}
                  max={7200}
                  controlSize="sm"
                  style={{ maxWidth: 160 }}
                  value={timeoutOverrideSeconds}
                  onChange={(e) => setTimeoutOverrideSeconds(e.target.value)}
                  placeholder="예: 1200"
                />
              )}
            </Field>
          )}
        </div>

        <Card title="영향 범위 미리보기">
          <div className="documents-preview">
            {impactLoading && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                <Spinner size={14} /> 계산 중...
              </div>
            )}
            {impactError && <ErrorText error={impactErrorObj} message="영향 범위를 불러오지 못했습니다." />}
            {impact && !impactLoading && (
              <>
                <div><strong>재실행 블록:</strong> {impact.affectedBlocks.length > 0 ? impact.affectedBlocks.join(' → ') : '없음'}</div>
                {mode === 'specific' && reusedLabels.length > 0 && (
                  <div><strong>캐시 재사용:</strong> {reusedLabels.join(', ')}</div>
                )}
                <div className="documents-preview-meta">
                  <span>영향 노드 수: {impact.affectedNodeCount}</span>
                  <span>영향 청크 수: {impact.affectedChunkCount}</span>
                </div>
                {impact.fullReprocessingRequired && (
                  <span className="documents-text-warning" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}>
                    <AlertTriangle size={13} aria-hidden="true" /> 하위 사전/설정 변경으로 전체 재처리가 필요합니다.
                  </span>
                )}
              </>
            )}
          </div>
        </Card>

        <Field label="사유 (선택)">
          {(id) => (
            <Textarea
              id={id}
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="재처리 사유를 입력하세요"
            />
          )}
        </Field>

        {startReprocess.isError && (
          <ErrorAlert error={startReprocess.error} message="재처리를 시작하지 못했습니다." />
        )}
      </div>
    </Modal>
  )
}
