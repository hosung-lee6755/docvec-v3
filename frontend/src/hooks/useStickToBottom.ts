import { useCallback, useLayoutEffect, useRef } from 'react'

// 이만큼 안쪽이면 "맨 아래를 보고 있다"고 본다(마지막 줄이 조금 덜 보여도 따라가게)
const NEAR_BOTTOM_PX = 120

/**
 * 대화 목록처럼 아래로 자라는 스크롤 영역을 맨 아래에 붙여 둔다.
 * - 처음 열 때와 `contentKey`가 바뀔 때(새 메시지, 답변이 이어 써질 때) 맨 아래로 내린다.
 * - 사용자가 위로 올려 이전 내용을 읽고 있으면 끌어내리지 않는다.
 * - `stickNow()`를 부르면(질문을 보낸 직후) 위치와 관계없이 다음 변경 때 맨 아래로 내린다.
 */
export function useStickToBottom<T extends HTMLElement>(contentKey: string, resetKey: string) {
  const ref = useRef<T>(null)
  const isPinned = useRef(true)

  const handleScroll = useCallback(() => {
    const el = ref.current
    if (!el) return
    isPinned.current = el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX
  }, [])

  const stickNow = useCallback(() => {
    isPinned.current = true
  }, [])

  // 다른 대화로 옮기면 다시 맨 아래부터 보여 준다
  useLayoutEffect(() => {
    isPinned.current = true
  }, [resetKey])

  useLayoutEffect(() => {
    const el = ref.current
    if (el && isPinned.current) el.scrollTop = el.scrollHeight
  }, [contentKey, resetKey])

  return { ref, handleScroll, stickNow }
}
