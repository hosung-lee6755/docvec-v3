import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import OcrConfidencePanel from './OcrConfidencePanel'

// 실패 응답을 실제 QueryClient로 흘리면 react-query 내부 promise의 거부가 테스트 실패로 잡힌다.
// 그래서 실패 상태는 useQuery를 흉내 내어 따로 확인한다.
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: undefined, isLoading: false, isError: true }),
}))

describe('OcrConfidencePanel error state', () => {
  it('shows an error instead of failing silently', () => {
    render(<OcrConfidencePanel documentId="doc-1" />)
    expect(screen.getByRole('alert')).toHaveTextContent('OCR 신뢰도를 불러오지 못했습니다')
  })
})
