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

  it('keeps "1.", "1)" and "-" markers as written instead of turning them into lists', () => {
    // 2026-11-26: 원문의 "1.", "1)", "-" 줄이 목록으로 바뀌고 화면 CSS(list-style: none)가 기호를 지워 기호가 사라졌다
    const source = '3. 사업 개요\n4. 추진 일정\n\n1) 데이터 수집\n2) 모형 개발\n\n- 항만 물동량\n- 선박 입출항'
    const { container } = render(<ReactMarkdown remarkPlugins={markdownPlugins}>{source}</ReactMarkdown>)

    expect(container.querySelector('ol, ul, li')).toBeNull()
    const lines = [...container.querySelectorAll('p')].map((p) => p.textContent)
    expect(lines).toEqual(['3. 사업 개요', '4. 추진 일정', '1) 데이터 수집', '2) 모형 개발', '- 항만 물동량', '- 선박 입출항'])
  })

  it('keeps nested list markers and empty items', () => {
    const { container } = render(<ReactMarkdown remarkPlugins={markdownPlugins}>{'1. 상위\n   - 하위\n-'}</ReactMarkdown>)

    expect(container.querySelector('ol, ul, li')).toBeNull()
    expect([...container.querySelectorAll('p')].map((p) => p.textContent)).toEqual(['1. 상위', '- 하위', '-'])
  })

  it('shows markdown-looking text as written', () => {
    // 2026-11-26 렌더링 대조: 본문은 평문인데 "# 주석", "[제목](괄호)", "*별표*" 가 마크다운으로 읽혀 글자가 사라졌다
    const source = [
      '# 관리자 계정으로 실행',
      '[기술제안서 평가항목 및 배점한도](일반SW개발사업)',
      '96*96 크기와 *강조처럼 보이는* 글, snake_case_name',
      '> 인용처럼 보이는 줄',
      '`코드처럼` 보이는 글과 <b>태그</b>',
      '제목처럼 보이는 줄\n===',
      '---',
    ]
    for (const line of source) {
      const { container } = render(<ReactMarkdown remarkPlugins={markdownPlugins}>{line}</ReactMarkdown>)

      expect(container.querySelector('h1, h2, a, em, strong, blockquote, code, hr, b')).toBeNull()
      expect(container.textContent?.replace(/\s+/g, '')).toBe(line.replace(/\s+/g, ''))
    }
  })

  it('still renders GFM tables', () => {
    const { container } = render(<ReactMarkdown remarkPlugins={markdownPlugins}>{'| a | b |\n|---|---|\n| 1 | 2 |'}</ReactMarkdown>)

    expect(container.querySelector('table')).not.toBeNull()
  })
})
