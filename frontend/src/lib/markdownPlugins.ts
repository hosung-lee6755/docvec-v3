import type { Options } from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * 파싱 본문을 그릴 때 쓰는 remark 플러그인.
 *
 * GFM 은 물결표 하나로 감싼 글("~글~")도 취소선으로 그린다. 우리 문서는 "06월 22일~07월 27일"처럼 기간과 범위를
 * 물결표로 적어, 한 줄에 범위가 둘 있으면 그 사이가 취소선이 되었다(만도 보고서, 2026-11-25). 표 등 다른 GFM 문법은 쓰고
 * 물결표 하나짜리 취소선만 끈다. 물결표 둘("~~글~~")은 그대로 취소선이다.
 */
export const markdownPlugins: NonNullable<Options['remarkPlugins']> = [[remarkGfm, { singleTilde: false }]]
