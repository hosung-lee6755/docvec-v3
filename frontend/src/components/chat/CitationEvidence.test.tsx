import { describe, it, expect } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CitationEvidence, LowOcrBadge } from './CitationEvidence'

describe('CitationEvidence', () => {
  it('stays collapsed until the reader opens it, then shows only computed scores', () => {
    render(<CitationEvidence evidence={{ scores: { vector: 0.81, fused: 0.7 }, matched_terms: ['매출', '분기'] }} />)
    const toggle = screen.getByRole('button', { name: /왜 근거가 됐나/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('의미 유사도')).not.toBeInTheDocument()

    fireEvent.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('의미 유사도')).toBeInTheDocument()
    expect(screen.getByText('융합')).toBeInTheDocument()
    // 재순위를 하지 않았으면 그 줄은 없다
    expect(screen.queryByText('재순위')).not.toBeInTheDocument()
    expect(screen.getByText('매출, 분기')).toBeInTheDocument()
  })

  it('renders nothing for masked or empty evidence', () => {
    const { container: masked } = render(<CitationEvidence evidence={null} />)
    expect(masked).toBeEmptyDOMElement()
    const { container: empty } = render(<CitationEvidence evidence={{ scores: {}, matched_terms: [] }} />)
    expect(empty).toBeEmptyDOMElement()
  })

  it('says the match was by meaning only when no terms overlapped', () => {
    render(<CitationEvidence evidence={{ scores: { vector: 0.5 }, matched_terms: [] }} />)
    fireEvent.click(screen.getByRole('button', { name: /왜 근거가 됐나/ }))
    expect(screen.getByText('없음(뜻으로만 찾음)')).toBeInTheDocument()
  })
})

describe('LowOcrBadge', () => {
  it('warns only when the page is below the OCR threshold', () => {
    const { rerender } = render(<LowOcrBadge evidence={{ ocr_confidence: 0.42, low_ocr: true }} />)
    expect(screen.getByText(/OCR 신뢰도 낮음 42%/)).toBeInTheDocument()

    rerender(<LowOcrBadge evidence={{ ocr_confidence: 0.9, low_ocr: false }} />)
    expect(screen.queryByText(/OCR 신뢰도 낮음/)).not.toBeInTheDocument()
  })
})
