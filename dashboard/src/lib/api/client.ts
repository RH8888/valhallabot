import axios from 'axios'
import { getAuthToken } from './token'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'
const API_TIMEOUT = Number(import.meta.env.VITE_API_TIMEOUT ?? 20000)

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: API_TIMEOUT,
})

apiClient.interceptors.request.use((config) => {
  const token = getAuthToken()
  if (token && !config.headers?.Authorization) {
    config.headers = {
      ...config.headers,
      Authorization: `Bearer ${token}`,
    }
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
)

export type ApiClient = typeof apiClient
