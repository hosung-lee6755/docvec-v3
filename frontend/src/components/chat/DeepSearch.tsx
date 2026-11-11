import { useState } from 'react'
import { ChevronDown, ChevronUp, Layers } from 'lucide-react'
import type { AgentSteps, DeepProgress } from '../../hooks/useChat'

// v3 마일스톤 5 — 심층 검색. 복합 질문을 하위 질문으로 나눠 따로 찾은 뒤 종합한다.
// 이 파일은 켜는 스위치, 생성 중 진행 단계, 끝난 뒤의 검색 과정을 그린다. 채팅과 답변 추적이 함께 쓴다.

const MUTED: React.CSSProperties = { fontSize: 12, color: 'var(--color-text-muted)' }

// KRDS가 기본 체크박스를 다시 그려 켜짐과 꺼짐이 구분되지 않으므로, 스위치를 직접 그린다.
// 켜지면 바탕이 강조색으로 차고 손잡이가 오른쪽으로 가며, 글자로도 "켜짐"을 보여 준다.
const TRACK_WIDTH = 32
const KNOB_SIZE = 14

export function DeepSearchToggle({ checked, onChange, disabled }: {
  checked: boolean; onChange: (value: boolean) => void; disabled?: boolean
}) {
  const accent = 'var(--color-accent)'
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      title="여러 문서와 조건이 얽힌 질문을 하위 질문으로 나눠 따로 찾은 뒤 종합합니다. 일반 질문보다 10~60초 더 걸립니다."
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 8, flexShrink: 0,
        padding: '6px 12px', borderRadius: 999, fontSize: 13, fontWeight: checked ? 700 : 500,
        border: `1.5px solid ${checked ? accent : 'var(--color-border)'}`,
        background: checked ? accent : 'transparent',
        color: checked ? '#fff' : 'var(--color-text-muted)',
        cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1,
        transition: 'background var(--duration-fast), color var(--duration-fast), border-color var(--duration-fast)',
      }}
    >
      <span aria-hidden="true" style={{
        position: 'relative', width: TRACK_WIDTH, height: KNOB_SIZE + 4, borderRadius: 999,
        background: checked ? 'rgba(255,255,255,0.35)' : 'var(--color-border)',
      }}>
        <span style={{
          position: 'absolute', top: 2, left: 2, width: KNOB_SIZE, height: KNOB_SIZE, borderRadius: '50%',
          background: '#fff', transform: `translateX(${checked ? TRACK_WIDTH - KNOB_SIZE - 4 : 0}px)`,
          transition: 'transform var(--duration-fast)',
        }} />
      </span>
      <Layers size={14} aria-hidden="true" />
      심층 검색
      <span aria-hidden="true" style={{ fontSize: 12 }}>{checked ? '켜짐' : '꺼짐'}</span>
    </button>
  )
}

const PHASE_LABELS: Record<DeepProgress['phase'], string> = {
  planning: '질문을 하위 질문으로 나누는 중',
  searching: '하위 질문별로 문서를 찾는 중',
  answering: '찾은 근거로 답을 종합하는 중',
  verifying: '답이 근거에 맞는지 확인하는 중',
}

export function DeepSearchProgress({ progress }: { progress: DeepProgress | null | undefined }) {
  const phase = progress?.phase ?? 'planning'
  const questions = progress?.subquestions ?? []
  return (
    <div role="status" aria-live="polite" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', padding: 'var(--space-4)', color: 'var(--color-text-muted)' }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <span className="krds-spinner" style={{ width: 14, height: 14 }} aria-hidden="true" />
        심층 검색: {PHASE_LABELS[phase]}
      </span>
      {questions.length > 1 && (
        <ol style={{ margin: 0, paddingLeft: 'var(--space-6)', fontSize: 13 }}>
          {questions.map((q, i) => {
            const isDone = phase !== 'searching' || i < (progress?.current ?? 0)
            const isCurrent = phase === 'searching' && i === progress?.current
            return (
              <li key={q} style={{ fontWeight: isCurrent ? 600 : 400, opacity: isDone || isCurrent ? 1 : 0.6 }}>
                {q}{isCurrent ? ' (찾는 중)' : isDone ? ' (완료)' : ''}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}

function seconds(ms: number | undefined): string {
  return ms === undefined ? '-' : `${(ms / 1000).toFixed(1)}초`
}

export function DeepSearchSteps({ steps, defaultOpen = false }: { steps: AgentSteps; defaultOpen?: boolean }) {
  const [isOpen, setIsOpen] = useState(defaultOpen)
  const timings = steps.timings_ms ?? {}
  const total = Object.values(timings).reduce((sum, v) => sum + (v ?? 0), 0)
  return (
    <section aria-label="심층 검색 과정">
      <button type="button" className="krds-btn text small" aria-expanded={isOpen} onClick={() => setIsOpen((v) => !v)}>
        {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        검색 과정 (하위 질문 {steps.subquestions.length}개 · 근거 {steps.evidence_count}건 · {seconds(total)})
      </button>
      {isOpen && (
        <div style={{ border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {!steps.decomposed && <p style={{ ...MUTED, margin: 0 }}>나눌 필요가 없는 질문이라 원래 질문 그대로 찾았습니다.</p>}
          {steps.fallback_to_original && <p style={{ ...MUTED, margin: 0 }}>하위 질문으로는 찾지 못해 원래 질문으로 다시 찾았습니다.</p>}
          <ol style={{ margin: 0, paddingLeft: 'var(--space-5)', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {steps.subquestions.map((q, i) => (
              <li key={`${i}-${q.question}`} style={{ fontSize: 13 }}>
                <span style={{ fontWeight: 600 }}>{q.question}</span>
                <span style={{ ...MUTED, display: 'block' }}>
                  검색 {q.searches}회{q.supplemented ? '(근거가 약해 한 번 더 찾음)' : ''} · 결과 {q.hit_count}건
                </span>
                {q.documents.length > 0 && (
                  <span style={{ ...MUTED, display: 'block' }}>
                    {q.documents.map((d, j) => (
                      <span key={j}>{j > 0 && ', '}{d.hidden ? '(볼 수 없는 문서)' : d.filename ?? '(이름 없음)'}</span>
                    ))}
                  </span>
                )}
              </li>
            ))}
          </ol>
          <p style={{ ...MUTED, margin: 0 }}>
            소요 시간: 질문 나누기 {seconds(timings.plan)}, 검색 {seconds(timings.search)}, 답변 {seconds(timings.answer)}, 근거 확인 {seconds(timings.verify)}
          </p>
        </div>
      )}
    </section>
  )
}
