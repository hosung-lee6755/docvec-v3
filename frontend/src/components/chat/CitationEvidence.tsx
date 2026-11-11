import { useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'

// v3 마일스톤 6 — 검색 결과가 근거가 된 이유. 채팅 인용, 검색 결과, 답변 추적이 함께 쓴다.
// 점수는 검색 단계에서 이미 계산한 값이다. 계산하지 않은 단계(예: 재순위를 끈 컬렉션)는 빠진다.

export interface RetrievalEvidence {
  scores?: { vector?: number; bm25?: number; fused?: number; rerank?: number }
  matched_terms?: string[]
  ocr_confidence?: number
  low_ocr?: boolean
}

const SCORE_LABELS: [keyof NonNullable<RetrievalEvidence['scores']>, string, string][] = [
  ['vector', '의미 유사도', '질문과 뜻이 얼마나 가까운지(벡터 유사도)'],
  ['bm25', '키워드', '질문의 낱말이 얼마나 들어 있는지(BM25, 후보 중 최고를 1로 맞춤)'],
  ['fused', '융합', '의미 유사도와 키워드를 컬렉션 설정의 비중으로 섞은 값'],
  ['rerank', '재순위', '질문과 본문을 함께 읽고 매긴 관련도(0~1)'],
]

function percent(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function LowOcrBadge({ evidence }: { evidence?: RetrievalEvidence | null }) {
  if (!evidence?.low_ocr) return null
  const confidence = evidence.ocr_confidence ?? 0
  return (
    <span
      className="krds-badge xsmall bg-warning"
      title={`이 쪽은 스캔 이미지를 글자로 읽은(OCR) 신뢰도가 ${percent(confidence)}로 낮습니다. 원문과 다를 수 있으니 문서를 열어 확인하세요.`}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
    >
      <AlertTriangle size={11} aria-hidden="true" />
      OCR 신뢰도 낮음 {percent(confidence)}
    </span>
  )
}

export function CitationEvidence({ evidence }: { evidence?: RetrievalEvidence | null }) {
  const [isOpen, setIsOpen] = useState(false)
  if (!evidence) return null
  const scores = SCORE_LABELS.filter(([key]) => evidence.scores?.[key] !== undefined)
  const terms = evidence.matched_terms ?? []
  if (scores.length === 0 && terms.length === 0 && evidence.ocr_confidence === undefined) return null
  return (
    <div style={{ marginTop: 'var(--space-2)' }}>
      <button type="button" className="krds-btn text small" aria-expanded={isOpen} onClick={() => setIsOpen((v) => !v)}
        style={{ fontSize: 12, padding: 0 }}>
        {isOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        왜 근거가 됐나
      </button>
      {isOpen && (
        <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '2px var(--space-3)', margin: 'var(--space-1) 0 0', fontSize: 12 }}>
          {scores.map(([key, label, help]) => (
            <ScoreRow key={key} label={label} help={help} value={evidence.scores?.[key] ?? 0} />
          ))}
          <dt style={{ color: 'var(--color-text-muted)' }}>겹친 낱말</dt>
          <dd style={{ margin: 0 }}>{terms.length ? terms.join(', ') : '없음(뜻으로만 찾음)'}</dd>
          {evidence.ocr_confidence !== undefined && (
            <>
              <dt style={{ color: 'var(--color-text-muted)' }}>OCR 신뢰도</dt>
              <dd style={{ margin: 0 }}>{percent(evidence.ocr_confidence)}{evidence.low_ocr ? ' (기준 미달)' : ''}</dd>
            </>
          )}
        </dl>
      )}
    </div>
  )
}

function ScoreRow({ label, help, value }: { label: string; help: string; value: number }) {
  // 점수는 대부분 0~1이다. 막대는 그 범위로 자르고, 숫자는 그대로 보여 준다.
  const width = Math.max(0, Math.min(1, value)) * 100
  return (
    <>
      <dt style={{ color: 'var(--color-text-muted)' }} title={help}>{label}</dt>
      <dd style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <span aria-hidden="true" style={{ width: 80, height: 6, borderRadius: 3, background: '#e2e8f0', overflow: 'hidden' }}>
          <span style={{ display: 'block', width: `${width}%`, height: '100%', background: 'var(--color-accent)' }} />
        </span>
        {value.toFixed(3)}
      </dd>
    </>
  )
}
