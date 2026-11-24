import type { ComponentPropsWithoutRef } from 'react'

import { splitAutolink } from '../../lib/autolink'

type MarkdownLinkProps = ComponentPropsWithoutRef<'a'> & { node?: unknown }

/**
 * 파싱 텍스트 마크다운의 링크. GFM 자동 링크는 실제 주소 부분만 링크로 두고 뒤에 붙은 글은 그대로 보인다
 * ("www.ntis.go.kr)에" → 링크 "www.ntis.go.kr" + ")에"). 문서 속 링크는 새 창으로 연다.
 */
export function MarkdownLink({ href, children, node: _node, ...rest }: MarkdownLinkProps) {
  const text = typeof children === 'string' ? children : null
  const parts = text ? splitAutolink(text) : null
  if (parts && parts.rest) {
    return (
      <>
        <a {...rest} href={parts.href} target="_blank" rel="noopener noreferrer">{parts.label}</a>
        {parts.rest}
      </>
    )
  }
  return <a {...rest} href={href} target="_blank" rel="noopener noreferrer">{children}</a>
}
