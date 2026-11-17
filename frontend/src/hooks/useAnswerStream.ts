import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { parseSse } from '../lib/sse'
import { useAuthStore } from '../store/authStore'
import type { ChatMessage, ConversationDetail, DeepProgress } from './useChat'

// 전체 점검 2-5 — 만들고 있는 답변을 SSE로 받아 대화 캐시에 바로 넣는다.
// 연결이 끊기거나 열리지 않으면 false를 돌려주고, 화면은 기존 주기 조회로 이어 간다.

function patchMessage(
  conversation: ConversationDetail | undefined,
  messageId: string,
  patch: (message: ChatMessage) => ChatMessage,
): ConversationDetail | undefined {
  if (!conversation) return conversation
  return {
    ...conversation,
    messages: conversation.messages.map((message) => (message.id === messageId ? patch(message) : message)),
  }
}

// 주기 조회가 조금 더 늦은 값을 이미 넣었을 수 있다. 글이 뒤로 줄어들지 않게 더 긴 쪽을 남긴다
export function withPartial(message: ChatMessage, text: string): ChatMessage {
  return text.length > (message.partial_answer ?? '').length ? { ...message, partial_answer: text } : message
}

async function readStream(
  messageId: string,
  signal: AbortSignal,
  onEvent: (event: string, data: unknown) => void,
): Promise<void> {
  const token = useAuthStore.getState().accessToken
  const response = await fetch(`/api/v1/chat/${messageId}/stream`, {
    headers: { Accept: 'text/event-stream', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    signal,
  })
  if (!response.ok || !response.body) throw new Error(`stream ${response.status}`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) return
    const parsed = parseSse(buffer + decoder.decode(value, { stream: true }))
    buffer = parsed.rest
    for (const item of parsed.events) onEvent(item.event, JSON.parse(item.data))
  }
}

export function useAnswerStream(conversationId: string, messageId: string | null): boolean {
  const queryClient = useQueryClient()
  const [streamingId, setStreamingId] = useState<string | null>(null)

  useEffect(() => {
    if (!messageId) return
    const controller = new AbortController()
    const key = ['conversation', conversationId]
    const update = (patch: (message: ChatMessage) => ChatMessage) =>
      queryClient.setQueryData<ConversationDetail>(key, (old) => patchMessage(old, messageId, patch))

    setStreamingId(messageId)
    readStream(messageId, controller.signal, (event, data) => {
      if (event === 'partial') update((message) => withPartial(message, (data as { text: string }).text))
      if (event === 'progress') update((message) => ({ ...message, progress: data as DeepProgress }))
      if (event === 'done') void queryClient.invalidateQueries({ queryKey: key })
    })
      // 스트림이 실패해도 답변은 주기 조회로 계속 받는다. 여기서는 스트림만 내려놓는다
      .catch(() => undefined)
      .finally(() => {
        if (!controller.signal.aborted) setStreamingId(null)
      })
    return () => controller.abort()
  }, [conversationId, messageId, queryClient])

  return streamingId !== null && streamingId === messageId
}
