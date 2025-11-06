import { AxiosError } from 'axios'
import { toast } from 'sonner'
import { handleServerError } from '@/lib/handle-server-error'

export function shouldRetryApiRequest(failureCount: number, error: unknown) {
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.log({ failureCount, error })
  }

  if (failureCount <= 0 && import.meta.env.DEV) return false
  if (failureCount > 3 && import.meta.env.PROD) return false

  if (error instanceof AxiosError) {
    const status = error.response?.status ?? 0
    if (status === 401 || status === 403) {
      return false
    }
  }

  return true
}

interface QueryErrorHandlers {
  onUnauthorized?: () => void
  onServerError?: () => void
  onForbidden?: () => void
}

export function handleQueryError(error: unknown, handlers: QueryErrorHandlers = {}) {
  if (error instanceof AxiosError) {
    const status = error.response?.status
    if (status === 401) {
      toast.error('Session expired!')
      handlers.onUnauthorized?.()
      return
    }
    if (status === 500) {
      toast.error('Internal Server Error!')
      handlers.onServerError?.()
      return
    }
    if (status === 403) {
      toast.error('You do not have permission to perform this action.')
      handlers.onForbidden?.()
      return
    }
  }

  handleServerError(error)
}

export function handleMutationError(error: unknown) {
  handleServerError(error)

  if (error instanceof AxiosError && error.response?.status === 304) {
    toast.error('Content not modified!')
  }
}
