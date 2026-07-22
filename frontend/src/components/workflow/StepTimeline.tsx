import type { ReactNode } from 'react'
import { CheckCircle2, Loader2, XCircle } from 'lucide-react'
import type { WorkflowRunStep } from '../../hooks/useWorkflows'

const STEP_STATUS_LABELS: Record<string, string> = {
  PENDING: '대기', RUNNING: '실행 중', COMPLETED: '완료', FAILED: '실패', SKIPPED: '건너뜀',
}

interface StepTimelineProps {
  steps: WorkflowRunStep[]
  // WorkflowRunsPage still resolves names from the version graph (blocks may
  // predate this endpoint returning `label`); the 처리 이력 tab can omit this
  // and rely on step.label (server-resolved from the block instance/registry).
  blockName?: (blockInstanceId: string) => string
  // Only the 처리 이력 tab passes this (renders "이 블록부터 재처리" per step) —
  // WorkflowRunsPage does not, per Phase 9 scope (그 페이지 자체 개편은 9d로 미룸).
  renderStepActions?: (step: WorkflowRunStep) => ReactNode
}

export default function StepTimeline({ steps, blockName, renderStepActions }: StepTimelineProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      {steps.map((step) => {
        const output = step.output
          ? Object.fromEntries(Object.entries(step.output).filter(([k]) => k !== 'text' && k !== 'changes'))
          : null
        return (
          <div key={step.id} style={{
            padding: 'var(--space-2)', background: '#f8fafc', borderRadius: 'var(--radius-sm)',
            display: 'flex', flexDirection: 'column', gap: 4,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 13 }}>
              {step.status === 'COMPLETED' && <CheckCircle2 size={14} style={{ color: '#16a34a' }} />}
              {step.status === 'FAILED' && <XCircle size={14} style={{ color: '#dc2626' }} />}
              {(step.status === 'PENDING' || step.status === 'RUNNING') && (
                <Loader2 size={14} style={{ animation: 'spin 1s linear infinite', color: '#2563eb' }} />
              )}
              <strong>{step.label ?? blockName?.(step.block_instance_id) ?? step.block_instance_id.slice(0, 8)}</strong>
              <span style={{ fontSize: 11, color: '#94a3b8' }}>
                {STEP_STATUS_LABELS[step.status] ?? step.status}
              </span>
              {step.cached && (
                <span className="krds-badge xsmall bg-secondary" title="이전 실행 결과를 그대로 재사용함">캐시</span>
              )}
              {renderStepActions && step.status === 'COMPLETED' && (
                <span style={{ marginLeft: 'auto' }}>{renderStepActions(step)}</span>
              )}
            </div>
            {step.error_message && (
              <div style={{ fontSize: 12, color: '#b91c1c' }}>{step.error_message}</div>
            )}
            {!!step.warnings?.length && (
              <div style={{ fontSize: 12, color: '#b45309' }}>
                {step.warnings.join(' · ')}
              </div>
            )}
            {output && Object.keys(output).length > 0 && (
              <pre style={{
                margin: 0, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                color: '#475569', maxHeight: 120, overflow: 'auto',
              }}>
                {JSON.stringify(output, null, 2)}
              </pre>
            )}
          </div>
        )
      })}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
