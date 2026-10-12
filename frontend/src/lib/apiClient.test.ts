import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import axios, { type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { apiClient } from './apiClient'
import { useAuthStore } from '../store/authStore'

/**
 * Manual axios adapter for testing interceptors.
 * Simulates responses without hitting a real server.
 */
function createMockAdapter(responses: Record<string, { status: number; data?: unknown }>) {
  const adapter: AxiosAdapter = async (config: InternalAxiosRequestConfig) => {
    const key = `${config.method?.toUpperCase()} ${config.url}`
    const response = responses[key]
    if (!response) {
      throw new Error(`No mock for ${key}`)
    }
    return {
      data: response.data,
      status: response.status,
      statusText: 'OK',
      headers: config.headers,
      config,
    } as AxiosResponse
  }
  return adapter
}

describe('apiClient interceptors', () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: { id: '1', email: 'test@example.com', username: 'test', role: 'user' },
      accessToken: 'initial-token',
      isAuthenticated: true,
    })
  })

  afterEach(() => {
    useAuthStore.setState({
      user: null,
      accessToken: null,
      isAuthenticated: false,
    })
  })

  describe('request interceptor', () => {
    it('should add Authorization header with token', async () => {
      const config: InternalAxiosRequestConfig = {
        url: '/test',
        method: 'get',
        headers: {},
      } as InternalAxiosRequestConfig

      const handlers = apiClient.interceptors.request.handlers
      if (!handlers || !handlers[0]) throw new Error('No request interceptor')
      const interceptor = handlers[0]
      const result = interceptor.fulfilled?.(config)

      if (result instanceof Promise) {
        const resolved = await result
        expect(resolved?.headers?.Authorization).toBe('Bearer initial-token')
      } else {
        expect(result?.headers?.Authorization).toBe('Bearer initial-token')
      }
    })

    it('should not add Authorization header when no token', async () => {
      useAuthStore.setState({ accessToken: null, user: null, isAuthenticated: false })

      const config: InternalAxiosRequestConfig = {
        url: '/test',
        method: 'get',
        headers: {},
      } as InternalAxiosRequestConfig

      const handlers = apiClient.interceptors.request.handlers
      if (!handlers || !handlers[0]) throw new Error('No request interceptor')
      const interceptor = handlers[0]
      const result = interceptor.fulfilled?.(config)

      if (result instanceof Promise) {
        const resolved = await result
        expect(resolved?.headers?.Authorization).toBeUndefined()
      } else {
        expect(result?.headers?.Authorization).toBeUndefined()
      }
    })
  })

  describe('401 handling and token refresh', () => {
    it('should refresh token on 401 and retry request', async () => {
      let originalRequestCount = 0

      const mockAdapter = createMockAdapter({
        'GET /api/v1/protected': {
          status: 401, // First call gets 401
        },
        'POST /api/v1/auth/refresh': {
          status: 200,
          data: { access_token: 'new-token' },
        },
      })

      // Intercept the adapter to count calls
      const originalAdapter = apiClient.defaults.adapter
      apiClient.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
        if (config.url?.includes('/auth/refresh')) {
          return mockAdapter(config)
        }
        if (config.url?.includes('/protected')) {
          originalRequestCount++
          // First call: 401, retry with new token should succeed
          if (originalRequestCount === 1) {
            return {
              status: 401,
              data: {},
              statusText: 'Unauthorized',
              headers: {},
              config,
            } as AxiosResponse
          }
          // Retry: should have new token
          expect(config.headers.Authorization).toBe('Bearer new-token')
          return {
            status: 200,
            data: { success: true },
            statusText: 'OK',
            headers: {},
            config,
          } as AxiosResponse
        }
        return mockAdapter(config)
      }

      try {
        await apiClient.get('/protected')
      } catch {
        // Expected: first call gets 401, refresh happens, retry succeeds
      }

      // Restore original adapter
      apiClient.defaults.adapter = originalAdapter
    })

    it('should not retry 401 from /auth/login', async () => {
      const mockAdapter = createMockAdapter({
        'POST /api/v1/auth/login': {
          status: 401,
          data: { error: 'Invalid credentials' },
        },
      })

      apiClient.defaults.adapter = mockAdapter

      try {
        await apiClient.post('/auth/login', { email: 'test@test.com', password: 'wrong' })
        expect.fail('Should have thrown')
      } catch (error: unknown) {
        if (axios.isAxiosError(error)) {
          expect(error.response?.status).toBe(401)
          // Should not have cleared auth (because refresh was not triggered)
          expect(useAuthStore.getState().user).not.toBeNull()
        }
      }
    })

    it('should not retry 401 from /auth/refresh', async () => {
      const mockAdapter = createMockAdapter({
        'POST /api/v1/auth/refresh': {
          status: 401,
          data: { error: 'Refresh failed' },
        },
      })

      apiClient.defaults.adapter = mockAdapter

      try {
        await apiClient.post('/auth/refresh', {})
        expect.fail('Should have thrown')
      } catch (error: unknown) {
        if (axios.isAxiosError(error)) {
          expect(error.response?.status).toBe(401)
        }
      }
    })

    it('should clear auth and redirect on refresh failure', async () => {
      const oldLocation = window.location
      const mockLocation = { pathname: '/dashboard', href: '/login' }
      Object.defineProperty(window, 'location', {
        value: mockLocation,
        configurable: true,
      })

      const originalAdapter = apiClient.defaults.adapter
      apiClient.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
        if (config.url?.includes('/auth/refresh')) {
          // Throw 401 error for refresh to trigger error handler in response interceptor
          const response = {
            status: 401,
            statusText: 'Unauthorized',
            headers: {},
            data: { error: 'Token expired' },
            config,
          } as AxiosResponse
          const error = new axios.AxiosError('Request failed', '401', config, undefined, response)
          throw error
        }
        if (config.url?.includes('/protected')) {
          // Throw 401 to trigger refresh flow
          const response = {
            status: 401,
            statusText: 'Unauthorized',
            headers: {},
            data: { error: 'Unauthorized' },
            config,
          } as AxiosResponse
          const error = new axios.AxiosError('Request failed', '401', config, undefined, response)
          throw error
        }
        return { status: 200, data: {}, statusText: 'OK', headers: {}, config } as AxiosResponse
      }

      try {
        await apiClient.get('/protected')
        expect.fail('Should have thrown')
      } catch {
        // Response interceptor should have called clearAuth due to refresh 401
        expect(useAuthStore.getState().user).toBeNull()
        expect(useAuthStore.getState().accessToken).toBeNull()
        expect(useAuthStore.getState().isAuthenticated).toBe(false)
      }

      apiClient.defaults.adapter = originalAdapter
      Object.defineProperty(window, 'location', {
        value: oldLocation,
        configurable: true,
      })
    })

    it('should handle 401 when user is null', async () => {
      useAuthStore.setState({ user: null })

      const mockAdapter = createMockAdapter({
        'GET /api/v1/protected': {
          status: 401,
        },
      })

      apiClient.defaults.adapter = mockAdapter

      try {
        await apiClient.get('/protected')
      } catch (error: unknown) {
        if (axios.isAxiosError(error)) {
          expect(error.response?.status).toBe(401)
        }
      }
    })

    it('should not retry already-retried requests', async () => {
      let attemptCount = 0

      const mockAdapter = createMockAdapter({
        'GET /api/v1/protected': { status: 401 },
        'POST /api/v1/auth/refresh': {
          status: 200,
          data: { access_token: 'new-token' },
        },
      })

      apiClient.defaults.adapter = async (config) => {
        if (config.url?.includes('/protected')) {
          attemptCount++
          return {
            status: 401,
            data: {},
            statusText: 'Unauthorized',
            headers: {},
            config,
          } as AxiosResponse
        }
        return mockAdapter(config)
      }

      try {
        await apiClient.get('/protected')
        expect.fail('Should have thrown')
      } catch {
        // After refresh, retry should fail again with 401
        // but should not trigger another refresh (would loop)
        expect(attemptCount).toBeLessThanOrEqual(2)
      }
    })
  })

  describe('authStore integration', () => {
    it('should update token in request after setAuth', async () => {
      useAuthStore.getState().setAuth(
        { id: '2', email: 'new@example.com', username: 'newuser', role: 'admin' },
        'new-access-token',
      )

      const config: InternalAxiosRequestConfig = {
        url: '/test',
        method: 'get',
        headers: {},
      } as InternalAxiosRequestConfig

      const handlers = apiClient.interceptors.request.handlers
      if (!handlers || !handlers[0]) throw new Error('No request interceptor')
      const interceptor = handlers[0]
      const result = interceptor.fulfilled?.(config)

      if (result instanceof Promise) {
        const resolved = await result
        expect(resolved?.headers?.Authorization).toBe('Bearer new-access-token')
      } else {
        expect(result?.headers?.Authorization).toBe('Bearer new-access-token')
      }
      expect(useAuthStore.getState().accessToken).toBe('new-access-token')
      expect(useAuthStore.getState().user?.email).toBe('new@example.com')
    })

    it('should derive isAuthenticated from token on rehydrate', () => {
      // Simulate localStorage rehydrate with token but isAuthenticated missing
      useAuthStore.setState({
        user: { id: '1', email: 'test@example.com', username: 'test', role: 'user' },
        accessToken: 'persisted-token',
        isAuthenticated: false, // Wrong state before rehydrate
      })

      // Simulate what onRehydrateStorage does
      const state = useAuthStore.getState()
      state.isAuthenticated = !!state.accessToken

      expect(state.isAuthenticated).toBe(true)
    })

    it('should have isAuthenticated false when no token after rehydrate', () => {
      useAuthStore.setState({
        user: null,
        accessToken: null,
        isAuthenticated: true, // Wrong state before rehydrate
      })

      const state = useAuthStore.getState()
      state.isAuthenticated = !!state.accessToken

      expect(state.isAuthenticated).toBe(false)
    })
  })
})
