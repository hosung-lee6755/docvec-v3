// 전체 점검 2-5 — 서버가 보내는 SSE 본문을 이벤트로 나눈다.
// EventSource는 Authorization 헤더를 실을 수 없어서 fetch로 읽고 직접 나눈다.

export interface SseEvent {
  event: string
  data: string
}

export interface SseParseResult {
  events: SseEvent[]
  // 아직 끝나지 않은 마지막 이벤트의 앞부분. 다음 조각 앞에 붙여 다시 넘긴다
  rest: string
}

const EVENT_SEPARATOR = /\r?\n\r?\n/

function parseBlock(block: string): SseEvent | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split(/\r?\n/)) {
    // 콜론으로 시작하는 줄은 연결 유지용 주석이다
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '')
    if (field === 'event') event = value
    if (field === 'data') data.push(value)
  }
  return data.length > 0 ? { event, data: data.join('\n') } : null
}

export function parseSse(buffer: string): SseParseResult {
  const blocks = buffer.split(EVENT_SEPARATOR)
  const rest = blocks.pop() ?? ''
  const events = blocks.map(parseBlock).filter((item): item is SseEvent => item !== null)
  return { events, rest }
}
