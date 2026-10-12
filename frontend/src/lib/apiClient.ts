import axios, { AxiosError } from 'axios'
import { useAuthStore } from '../store/authStore'

export const apiClient = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
})

// Shared in-flight refresh promise to prevent N parallel refresh calls
let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const state = useAuthStore.getState()
  const user = state.user

  // If no user data, cannot refresh — must logout
  if (!user) {
    throw new Error('No user data available for refresh')
  }

  try {
    const { data } = await axios.post('/api/v1/auth/refresh', {}, { withCredentials: true })
    state.setAuth(user, data.access_token)
    return data.access_token
  } catch (error) {
    state.clearAuth()
    throw error
  }
}

apiClient.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Check if this is a 401 and not a retry (to avoid infinite loops)
    const is401 = error.response?.status === 401
    const hasRetried = originalRequest._retry === true
    const isAuthEndpoint = originalRequest.url?.includes('/auth/login') || originalRequest.url?.includes('/auth/refresh')

    if (is401 && !hasRetried && !isAuthEndpoint) {
      originalRequest._retry = true

      try {
        // Use shared refresh promise to handle parallel 401s
        if (!refreshPromise) {
          refreshPromise = refreshAccessToken()
        }

        const newToken = await refreshPromise

        // Clear the promise after successful refresh
        refreshPromise = null

        // Update the failed request with new token and retry
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return apiClient(originalRequest)
      } catch (refreshError) {
        // Refresh failed — logout and do not retry
        refreshPromise = null
        useAuthStore.getState().clearAuth()

        // Only redirect once
        if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
          window.location.href = '/login'
        }

        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  },
)

export type { AxiosError }
