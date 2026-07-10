import { describe, it, expect, beforeEach } from 'vitest'
import { useAuthStore } from '../store/authStore'

const mockUser = { id: '1', email: 'test@test.com', username: 'test', role: 'editor' }

describe('authStore', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, accessToken: null, isAuthenticated: false })
  })

  it('sets auth correctly', () => {
    useAuthStore.getState().setAuth(mockUser, 'token-123')
    const state = useAuthStore.getState()
    expect(state.isAuthenticated).toBe(true)
    expect(state.user?.email).toBe('test@test.com')
    expect(state.accessToken).toBe('token-123')
  })

  it('clears auth correctly', () => {
    useAuthStore.getState().setAuth(mockUser, 'token-123')
    useAuthStore.getState().clearAuth()
    const state = useAuthStore.getState()
    expect(state.isAuthenticated).toBe(false)
    expect(state.user).toBeNull()
    expect(state.accessToken).toBeNull()
  })
})
