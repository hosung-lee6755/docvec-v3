import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface Project {
  id: string
  name: string
  description: string | null
  system_prompt?: string | null
  created_at: string
  updated_at: string
  collection_count: number
  member_count: number
  is_owner: boolean
  role: 'owner' | 'editor' | 'viewer' | null
}

export interface ProjectListResponse {
  items: Project[]
}

export interface ProjectMember {
  user_id: string
  email: string
  username: string
  role: 'owner' | 'editor' | 'viewer'
  created_at: string | null
}

export interface ProjectMemberListResponse {
  items: ProjectMember[]
}

export interface CreateProjectInput {
  name: string
  description?: string
}

export interface UpdateProjectInput {
  id: string
  name?: string
  description?: string
}

export interface InviteProjectMemberInput {
  projectId: string
  email: string
  role: 'viewer' | 'editor'
}

export function useProjects() {
  return useQuery<ProjectListResponse>({
    queryKey: ['projects'],
    queryFn: async () => {
      const { data } = await apiClient.get('/projects')
      return data
    },
  })
}

export function useProject(id: string | null) {
  return useQuery<Project>({
    queryKey: ['project', id],
    queryFn: async () => {
      const { data } = await apiClient.get(`/projects/${id}`)
      return data
    },
    enabled: !!id,
  })
}

export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: CreateProjectInput) => {
      const { data } = await apiClient.post('/projects', input)
      return data as Project
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

export function useUpdateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...input }: UpdateProjectInput) => {
      const { data } = await apiClient.patch(`/projects/${id}`, input)
      return data as Project
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

export function useDeleteProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/projects/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['collections'] })
    },
  })
}

export function useSetProjectSystemPrompt() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, systemPrompt }: { id: string; systemPrompt: string | null }) => {
      const { data } = await apiClient.put(`/projects/${id}/system-prompt`, {
        system_prompt: systemPrompt,
      })
      return data as Project
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['project', variables.id] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

export interface ProjectApiKeyStatus {
  provider: 'openai' | 'anthropic'
  registered: boolean
  updated_at: string | null
}

export function useProjectApiKeys(projectId: string | null) {
  return useQuery<{ items: ProjectApiKeyStatus[] }>({
    queryKey: ['project-api-keys', projectId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/projects/${projectId}/api-keys`)
      return data
    },
    enabled: !!projectId,
  })
}

export function useSetProjectApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ projectId, provider, apiKey }: { projectId: string; provider: string; apiKey: string }) => {
      const { data } = await apiClient.put(`/projects/${projectId}/api-keys/${provider}`, { api_key: apiKey })
      return data as { message: string; provider: string }
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['project-api-keys', variables.projectId] })
    },
  })
}

export function useDeleteProjectApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ projectId, provider }: { projectId: string; provider: string }) => {
      await apiClient.delete(`/projects/${projectId}/api-keys/${provider}`)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['project-api-keys', variables.projectId] })
    },
  })
}

export function useProjectMembers(projectId: string | null) {
  return useQuery<ProjectMemberListResponse>({
    queryKey: ['project-members', projectId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/projects/${projectId}/members`)
      return data
    },
    enabled: !!projectId,
  })
}

export function useInviteProjectMember() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ projectId, email, role }: InviteProjectMemberInput) => {
      const { data } = await apiClient.post(`/projects/${projectId}/invite`, { email, role })
      return data as { message: string; email: string; role: string }
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['project-members', variables.projectId] })
    },
  })
}

export function useRemoveProjectMember() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ projectId, userId }: { projectId: string; userId: string }) => {
      await apiClient.delete(`/projects/${projectId}/members/${userId}`)
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['project-members', variables.projectId] })
    },
  })
}
