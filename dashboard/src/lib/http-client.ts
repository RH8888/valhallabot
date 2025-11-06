import { apiClient } from '@/lib/api/client'
import { setAuthToken } from '@/lib/api/token'

export const httpClient = apiClient

export function applyAuthToken(token?: string | null) {
  const resolvedToken = token ?? null
  setAuthToken(resolvedToken)

  if (resolvedToken) {
    httpClient.defaults.headers.common.Authorization = `Bearer ${resolvedToken}`
    return
  }

  delete httpClient.defaults.headers.common.Authorization
}
