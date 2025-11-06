import { httpClient } from '@/lib/http-client'
import type { Identity } from '@/types/auth'

type WhoAmIResponse = Identity

export async function fetchWhoAmI(token: string): Promise<WhoAmIResponse> {
  const response = await httpClient.get<WhoAmIResponse>('/identity/whoami', {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })

  return response.data
}

export async function rotateToken(role: Identity['role']): Promise<string> {
  if (role === 'agent') {
    const response = await httpClient.post<{ api_token: string }>('/agents/me/token')
    return response.data.api_token
  }

  if (role === 'super_admin') {
    const response = await httpClient.post<{ api_token: string }>('/admin/token')
    return response.data.api_token
  }

  throw new Error('Only agents and super admins can rotate tokens from the dashboard.')
}
