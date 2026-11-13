import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface User {
  id: string
  email: string
  username: string
  role: string
  // 관리자가 발급하거나 초기화한 임시 비밀번호 상태. 참이면 비밀번호 변경 화면부터 보여 준다
  must_change_password?: boolean
}

interface AuthState {
  user: User | null
  accessToken: string | null
  isAuthenticated: boolean // Derived from accessToken
  setAuth: (user: User, token: string) => void
  updateUser: (patch: Partial<User>) => void
  clearAuth: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      isAuthenticated: false, // Will be derived below

      setAuth: (user, accessToken) =>
        set({
          user,
          accessToken,
          isAuthenticated: !!accessToken,
        }),

      updateUser: (patch) =>
        set((state) => (state.user ? { user: { ...state.user, ...patch } } : state)),

      clearAuth: () =>
        set({
          user: null,
          accessToken: null,
          isAuthenticated: false,
        }),
    }),
    {
      name: 'docvec-auth',
      // Only persist user and token; derive isAuthenticated from token
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
      }),
      // Rehydrate: restore user/token and derive isAuthenticated
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.isAuthenticated = !!state.accessToken
        }
      },
    },
  ),
)
