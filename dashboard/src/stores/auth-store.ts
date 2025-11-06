import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { applyAuthToken } from '@/lib/http-client'
import type { Identity } from '@/types/auth'

interface AuthState {
  token: string | null
  identity: Identity | null
  isAuthenticated: () => boolean
  setSession: (token: string, identity: Identity) => void
  updateToken: (token: string) => void
  clearSession: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      identity: null,
      isAuthenticated: () => Boolean(get().token),
      setSession: (token, identity) => {
        applyAuthToken(token)
        set({ token, identity })
      },
      updateToken: (token) => {
        applyAuthToken(token)
        set((state) => ({ ...state, token }))
      },
      clearSession: () => {
        applyAuthToken(null)
        set({ token: null, identity: null })
      },
    }),
    {
      name: 'valhalla-auth',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ token: state.token, identity: state.identity }),
      onRehydrateStorage: () => (state, error) => {
        if (error) {
          // eslint-disable-next-line no-console
          console.error('Failed to rehydrate auth store', error)
          return
        }
        if (state?.token) {
          applyAuthToken(state.token)
        }
      },
    }
  )
)
