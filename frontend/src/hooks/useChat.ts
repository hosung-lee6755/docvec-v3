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
}

export interface ChatMessage {
  id: string
  status: 'PENDING' | 'GENERATING' | 'DONE' | 'FAILED'
  query: string
  answer: string | null
  citations: ChatCitation[] | null
  error_message: string | null
  created_at: string
  partial_answer?: string | null
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

export function useConversation(id: string | null) {
  return useQuery<ConversationDetail>({
    queryKey: ['conversation', id],
    queryFn: async () => {
      const { data } = await apiClient.get(`/chat/conversations/${id}`)
      return data
    },
    enabled: !!id,
    refetchInterval: (query) => (query.state.data?.messages.some(isPending) ? 1500 : false),
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
    mutationFn: async (query: string) => {
      const { data } = await apiClient.post(`/chat/conversations/${conversationId}/messages`, {
        query,
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
