import type { RetrievalEvidence } from '../components/chat/CitationEvidence'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface ChatModelOption {
  key: string
  label: string
  backend: 'local' | 'openai' | 'anthropic'
  available: boolean
}

export interface ChatCitation {
  index: number
  document_id: string | null
  collection_id: string | null
  collection_name: string | null
  filename: string | null
  page_number: number | null
  text: string
  // 지금 볼 수 없는 문서의 인용이면 true다. 서버가 본문·파일명·문서 id를 비워서 보낸다.
  hidden?: boolean
  // v3 마일스톤 6: 근거가 된 이유(점수, 겹친 낱말, 쪽의 OCR 신뢰도). 가린 인용에는 없다
  evidence?: RetrievalEvidence | null
  // 원문에서 근거 자리를 표시할 때 쓰는 청크 id. 예전 답변과 가린 인용에는 없다
  chunk_id?: string | null
}

// v3 마일스톤 5 심층 검색 — 하위 질문별 검색 과정. 지금 볼 수 없는 문서는 서버가 가려서 보낸다.
export interface AgentStepDocument {
  document_id: string | null
  filename: string | null
  hidden?: boolean
}

export interface AgentStepQuestion {
  question: string
  searches: number
  supplemented: boolean
  hit_count: number
  documents: AgentStepDocument[]
}

export interface AgentSteps {
  subquestions: AgentStepQuestion[]
  decomposed: boolean
  fallback_to_original: boolean
  evidence_count: number
  timings_ms: { plan?: number; search?: number; answer?: number; verify?: number }
}

export interface DeepProgress {
  phase: 'planning' | 'searching' | 'answering' | 'verifying'
  subquestions?: string[]
  current?: number
}

export type ChatMode = 'standard' | 'deep'
export type FeedbackRating = 'up' | 'down'

export interface ChatMessage {
  id: string
  status: 'PENDING' | 'GENERATING' | 'DONE' | 'FAILED'
  query: string
  answer: string | null
  citations: ChatCitation[] | null
  error_message: string | null
  created_at: string
  partial_answer?: string | null
  mode?: ChatMode
  agent_steps?: AgentSteps | null
  progress?: DeepProgress | null
  // 사전의 검색어 확장으로 질문에 덧붙여 찾은 낱말
  expanded_terms?: string[] | null
  // 사용자 평가. 평가 전이면 null
  feedback?: FeedbackRating | null
  feedback_note?: string | null
}

export interface ConversationSummary {
  id: string
  title: string
  model_key: string
  project_id: string | null
  collection_id: string | null
  created_at: string
  updated_at: string
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[]
}

const isPending = (m: ChatMessage) => m.status === 'PENDING' || m.status === 'GENERATING'

export function useChatModels(projectId?: string) {
  return useQuery<{ items: ChatModelOption[]; default_system_prompt: string }>({
    queryKey: ['chat-models', projectId ?? null],
    queryFn: async () => {
      const { data } = await apiClient.get('/chat/models', {
        params: { project_id: projectId || undefined },
      })
      return data
    },
  })
}

export function useConversations(projectId?: string) {
  return useQuery<ConversationSummary[]>({
    queryKey: ['conversations', projectId ?? null],
    queryFn: async () => {
      const { data } = await apiClient.get('/chat/conversations', {
        params: { project_id: projectId || undefined },
      })
      return data
    },
  })
}

// 답변 스트림이 열려 있으면 글은 스트림으로 오므로 주기 조회는 느리게 돈다(전체 점검 2-5)
const POLL_MS = 1500
const POLL_WHILE_STREAMING_MS = 5000

export function useConversation(id: string | null, isStreaming = false) {
  return useQuery<ConversationDetail>({
    queryKey: ['conversation', id],
    queryFn: async () => {
      const { data } = await apiClient.get(`/chat/conversations/${id}`)
      return data
    },
    enabled: !!id,
    refetchInterval: (query) => {
      if (!query.state.data?.messages.some(isPending)) return false
      return isStreaming ? POLL_WHILE_STREAMING_MS : POLL_MS
    },
  })
}

// rating이 null이면 평가를 지운다. 끝나면 열려 있는 대화를 다시 불러 버튼 상태를 맞춘다.
export function useMessageFeedback() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: { messageId: string; rating: FeedbackRating | null; note?: string | null }) => {
      const { data } = await apiClient.put(`/chat/${input.messageId}/feedback`, {
        rating: input.rating,
        note: input.note ?? null,
      })
      return data as ChatMessage
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversation'] })
    },
  })
}

export function useCreateConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      query: string
      project_id?: string
      collection_id?: string
      model_key: string
      mode?: ChatMode
    }) => {
      const { data } = await apiClient.post('/chat/conversations', input)
      return data as ConversationDetail
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['conversation', data.id], data)
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function useSendMessage(conversationId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ query, mode = 'standard' }: { query: string; mode?: ChatMode }) => {
      const { data } = await apiClient.post(`/chat/conversations/${conversationId}/messages`, {
        query,
        mode,
      })
      return data as ChatMessage
    },
    onSuccess: (message) => {
      queryClient.setQueryData<ConversationDetail | undefined>(
        ['conversation', conversationId],
        (prev) => (prev ? { ...prev, messages: [...prev.messages, message] } : prev)
      )
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function useRenameConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, title }: { id: string; title: string }) => {
      const { data } = await apiClient.patch(`/chat/conversations/${id}`, { title })
      return data as ConversationSummary
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}

export function useDeleteConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/chat/conversations/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    },
  })
}
