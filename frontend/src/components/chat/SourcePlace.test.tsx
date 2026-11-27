import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SourcePlace } from './SourcePlace'

describe('SourcePlace', () => {
  it('labels the page and section path so readers know what it is', () => {
    render(<SourcePlace filename="복무규정.pdf" page_number={3} section_path={['제2장 복무', '제3조(근무제)']} />)

    expect(screen.getByText('문서 위치')).toBeTruthy()
    expect(screen.getByText(/제2장 복무 > 제3조\(근무제\)/)).toBeTruthy()
  })

  it('shows no location label when the chunk has no page or section', () => {
    render(<SourcePlace filename="메모.txt" />)

    expect(screen.queryByText('문서 위치')).toBeNull()
  })
})
