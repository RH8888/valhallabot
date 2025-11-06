import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export const httpClient = axios.create({
  baseURL: API_BASE_URL,
})

export function applyAuthToken(token?: string | null) {
  if (token) {
    httpClient.defaults.headers.common.Authorization = `Bearer ${token}`
    return
  }
  delete httpClient.defaults.headers.common.Authorization
}
