/**
 * GFM 자동 링크(www.…, https://…)에서 실제 주소 부분만 떼어 낸다.
 *
 * GFM 은 공백이 나올 때까지를 주소로 본다. 한국어는 주소 뒤에 조사가 바로 붙어
 * "(www.ntis.go.kr)에"가 `http://www.ntis.go.xn--kr)-568n/` 같은 엉뚱한 주소가 됐다(2026-11-23 화면 점검).
 * 주소에 쓸 수 있는 ASCII 글자까지만 주소로 보고, 끝의 문장 부호와 짝이 없는 닫는 괄호는 뺀다.
 */
export interface AutolinkParts {
  href: string
  label: string
  rest: string
}

const URL_CHARS = /^[A-Za-z0-9\-._~:/?#[\]@!$&'()*+,;=%]+/
const TRAILING_PUNCTUATION = /[.,;:!?'"]+$/
const AUTOLINK_START = /^(https?:\/\/|www\.)/i

function trimUnbalancedParens(url: string): string {
  let trimmed = url
  while (trimmed.endsWith(')')) {
    const opens = (trimmed.match(/\(/g) ?? []).length
    const closes = (trimmed.match(/\)/g) ?? []).length
    if (closes <= opens) break
    trimmed = trimmed.slice(0, -1)
  }
  return trimmed
}

/** 자동 링크 글이면 주소와 그 뒤 글로 나누고, 주소가 아니면 null. */
export function splitAutolink(text: string): AutolinkParts | null {
  if (!AUTOLINK_START.test(text)) return null
  const matched = text.match(URL_CHARS)?.[0] ?? ''
  let label = matched
  let previous = ''
  while (label !== previous) {
    previous = label
    label = trimUnbalancedParens(label.replace(TRAILING_PUNCTUATION, ''))
  }
  if (!AUTOLINK_START.test(label) || label.length <= 'www.'.length) return null
  const href = /^www\./i.test(label) ? `http://${label}` : label
  return { href, label, rest: text.slice(label.length) }
}
