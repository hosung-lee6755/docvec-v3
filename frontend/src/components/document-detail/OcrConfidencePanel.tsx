import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../lib/apiClient'

// v3 마일스톤 6 — 쪽별 OCR 신뢰도. 스캔 이미지를 글자로 읽은 쪽만 나온다.
// 기준(OCR_LOW_CONFIDENCE, 기본 50%)보다 낮은 쪽은 검색 결과와 인용에도 경고가 붙는다.

interface OcrPage {
  page_number: number
  confidence: number
  word_count: number | null
  low: boolean
}

interface OcrConfidence {
  ocr_used: boolean
  threshold: number
  page_count: number | null
  pages: OcrPage[]
  low_pages: number[]
  mean_confidence: number | null
}

const BAR_HEIGHT = 64

function useOcrConfidence(documentId: string) {
  return useQuery<OcrConfidence>({
    queryKey: ['documents', documentId, 'ocr-confidence'],
    queryFn: async () => (await apiClient.get(`/documents/${documentId}/ocr-confidence`)).data,
    enabled: !!documentId,
  })
}

export default function OcrConfidencePanel({ documentId }: { documentId: string }) {
  const { data, isLoading, isError } = useOcrConfidence(documentId)
  if (isLoading) return null
  if (isError) {
    return <p role="alert" style={{ fontSize: 12, color: '#dc2626', margin: 0 }}>OCR 신뢰도를 불러오지 못했습니다.</p>
  }
  if (!data || !data.pages.length) {
    return (
      <section aria-label="쪽별 OCR 신뢰도">
        <h3 style={{ fontSize: 14, margin: '0 0 var(--space-1)' }}>쪽별 OCR 신뢰도</h3>
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
          {data?.ocr_used
            ? 'OCR을 했지만 쪽별 신뢰도가 기록되지 않았습니다(클라우드 OCR은 신뢰도를 주지 않습니다).'
            : '이 문서는 글자를 파일에서 바로 읽어 OCR을 하지 않았습니다.'}
        </p>
      </section>
    )
  }

  const percent = (v: number) => `${Math.round(v * 100)}%`
  return (
    <section aria-label="쪽별 OCR 신뢰도">
      <h3 style={{ fontSize: 14, margin: '0 0 var(--space-1)' }}>쪽별 OCR 신뢰도</h3>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 var(--space-2)' }}>
        OCR로 읽은 {data.pages.length}쪽 · 평균 {data.mean_confidence != null ? percent(data.mean_confidence) : '-'} · 기준 {percent(data.threshold)}
        {data.low_pages.length > 0
          ? ` · 기준 미달 ${data.low_pages.length}쪽(${data.low_pages.join(', ')}쪽). 이 쪽에서 나온 검색 결과와 인용에는 경고가 붙습니다.`
          : ' · 기준 미달 쪽 없음'}
      </p>
      <div role="list" style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: BAR_HEIGHT + 18, overflowX: 'auto', paddingBottom: 2 }}>
        {data.pages.map((p) => (
          <div key={p.page_number} role="listitem"
            title={`${p.page_number}쪽 · 신뢰도 ${percent(p.confidence)}${p.word_count != null ? ` · 단어 ${p.word_count}개` : ''}${p.low ? ' · 기준 미달' : ''}`}
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 14 }}>
            <span style={{
              width: 12, height: Math.max(2, p.confidence * BAR_HEIGHT), borderRadius: 2,
              background: p.low ? '#f59e0b' : 'var(--color-accent)',
            }} />
            <span style={{ fontSize: 9, color: 'var(--color-text-muted)' }}>{p.page_number}</span>
            <span className="sr-only">{p.page_number}쪽 {percent(p.confidence)}{p.low ? ' 기준 미달' : ''}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
