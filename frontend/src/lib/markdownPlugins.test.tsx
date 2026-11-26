import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import ReactMarkdown from 'react-markdown'
import { markdownPlugins } from './markdownPlugins'

describe('markdownPlugins', () => {
  it('keeps "~" ranges as text instead of striking them through', () => {
    // 만도 보고서(2026-11-25): "2020년 06월 22일~07월 27일 ... 07월 30일~12월" 사이가 취소선으로 그려졌다
    const { container } = render(
      <ReactMarkdown remarkPlugins={markdownPlugins}>{'일자 : 06월 22일~07월 27일, 07월 30일~12월 11일'}</ReactMarkdown>,
    )

    expect(container.querySelector('del')).toBeNull()
    expect(container.textContent).toContain('22일~07월 27일, 07월 30일~12월')
  })

  it('still renders GFM tables', () => {
    const { container } = render(<ReactMarkdown remarkPlugins={markdownPlugins}>{'| a | b |\n|---|---|\n| 1 | 2 |'}</ReactMarkdown>)

    expect(container.querySelector('table')).not.toBeNull()
  })
})
