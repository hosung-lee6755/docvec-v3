import { useState } from 'react'
import { ChevronDown, ChevronUp, Layers } from 'lucide-react'
import type { AgentSteps, DeepProgress } from '../../hooks/useChat'
import { Button } from '../ui'
import '../../styles/screens/user.css'

// v3 마일스톤 5 — 심층 검색. 복합 질문을 하위 질문으로 나눠 따로 찾은 뒤 종합한다.
// 이 파일은 켜는 스위치, 생성 중 진행 단계, 끝난 뒤의 검색 과정을 그린다. 채팅과 답변 추적이 함께 쓴다.

// KRDS가 기본 체크박스를 다시 그려 켜짐과 꺼짐이 구분되지 않으므로, 스위치를 직접 그린다.
// 켜지면 바탕이 강조색으로 차고 손잡이가 오른쪽으로 가며, 글자로도 "켜짐"을 보여 준다.

export function DeepSearchToggle({ checked, onChange, disabled }: {
  checked: boolean; onChange: (value: boolean) => void; disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      title="여러 문서와 조건이 얽힌 질문을 하위 질문으로 나눠 따로 찾은 뒤 종합합니다. 일반 질문보다 10~60초 더 걸립니다."
      className="user-switch"
    >
      <span aria-hidden="true" className="user-switch__track">
        <span className="user-switch__knob" />
      </span>
      <Layers size={14} aria-hidden="true" />
      심층 검색
      <span aria-hidden="true" className="user-switch__state">{checked ? '켜짐' : '꺼짐'}</span>
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
    <div role="status" aria-live="polite" className="user-deep__status">
      <span className="user-deep__status-line">
        <span className="user-spinner" aria-hidden="true" />
        심층 검색: {PHASE_LABELS[phase]}
      </span>
      {questions.length > 1 && (
        <ol className="user-deep__list">
          {questions.map((q, i) => {
            const isDone = phase !== 'searching' || i < (progress?.current ?? 0)
            const isCurrent = phase === 'searching' && i === progress?.current
            const stateClass = isCurrent ? 'is-current' : isDone ? '' : 'is-pending'
            return (
              <li key={q} className={`user-deep__item ${stateClass}`}>
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
      <Button
        variant="ghost"
        size="sm"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((v) => !v)}
        icon={isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      >
        검색 과정 (하위 질문 {steps.subquestions.length}개 · 근거 {steps.evidence_count}건 · {seconds(total)})
      </Button>
      {isOpen && (
        <div className="user-deep__box">
          {!steps.decomposed && <p className="user-deep__muted">나눌 필요가 없는 질문이라 원래 질문 그대로 찾았습니다.</p>}
          {steps.fallback_to_original && <p className="user-deep__muted">하위 질문으로는 찾지 못해 원래 질문으로 다시 찾았습니다.</p>}
          <ol className="user-deep__steps">
            {steps.subquestions.map((q, i) => (
              <li key={`${i}-${q.question}`} className="user-deep__step">
                <span className="user-deep__step-title">{q.question}</span>
                <span className="user-deep__muted user-deep__muted-block">
                  검색 {q.searches}회{q.supplemented ? '(근거가 약해 한 번 더 찾음)' : ''} · 결과 {q.hit_count}건
                </span>
                {q.documents.length > 0 && (
                  <span className="user-deep__muted user-deep__muted-block">
                    {q.documents.map((d, j) => (
                      <span key={j}>{j > 0 && ', '}{d.hidden ? '(볼 수 없는 문서)' : d.filename ?? '(이름 없음)'}</span>
                    ))}
                  </span>
                )}
              </li>
            ))}
          </ol>
          <p className="user-deep__muted">
            소요 시간: 질문 나누기 {seconds(timings.plan)}, 검색 {seconds(timings.search)}, 답변 {seconds(timings.answer)}, 근거 확인 {seconds(timings.verify)}
          </p>
        </div>
      )}
    </section>
  )
}
