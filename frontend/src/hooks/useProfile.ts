import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface Profile {
  id: string
  email: string
  username: string
  role: string
  is_active: boolean
  system_prompt: string | null
  created_at: string
}

export function useProfile() {
  return useQuery<Profile>({
    queryKey: ['profile'],
    queryFn: async () => {
      const { data } = await apiClient.get('/users/me')
      return data
    },
  })
}

export function useUpdateProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (username: string) => {
      const { data } = await apiClient.patch('/users/me', { username })
      return data as Profile
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
    },
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: async ({ currentPassword, newPassword }: { currentPassword: string; newPassword: string }) => {
      const { data } = await apiClient.post('/users/me/password', {
        current_password: currentPassword,
        new_password: newPassword,
      })
      return data as { message: string }
    },
  })
}

export function useSetSystemPrompt() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (systemPrompt: string | null) => {
      const { data } = await apiClient.put('/users/me/system-prompt', { system_prompt: systemPrompt })
      return data as Profile
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] })
    },
  })
}
