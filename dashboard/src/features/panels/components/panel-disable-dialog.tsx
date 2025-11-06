import { useState } from 'react'
import { ShieldOff } from 'lucide-react'
import { isAxiosError } from 'axios'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ConfirmDialog } from '@/components/confirm-dialog'
import type { Panel } from '@/lib/api/types'
import { useDisablePanelMutation } from '@/lib/api/panels'

type PanelDisableDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  panel: Panel
}

type DisableResult = Record<string, unknown>

type RemoteCleanupEntry = {
  target?: string
  ok?: boolean
  status?: string
  message?: string
}

function collectRemoteErrors(result: unknown): string[] {
  if (!result || typeof result !== 'object') return []
  const data = result as DisableResult
  const messages: string[] = []

  const append = (value: unknown) => {
    if (typeof value === 'string' && value.trim()) {
      messages.push(value)
    }
  }

  const candidates = ['errors', 'remote_errors', 'warnings']
  for (const key of candidates) {
    const value = data[key]
    if (Array.isArray(value)) {
      value.forEach(append)
    }
  }

  const detail = data.detail
  if (Array.isArray(detail)) {
    detail.forEach(append)
  } else {
    append(detail)
  }

  const remoteCleanup = data.remote_cleanup
  if (Array.isArray(remoteCleanup)) {
    for (const entry of remoteCleanup as RemoteCleanupEntry[]) {
      if (entry && typeof entry === 'object' && entry.ok === false) {
        const label = entry.target ?? entry.status ?? 'remote target'
        if (entry.message) {
          messages.push(`${label}: ${entry.message}`)
        } else {
          messages.push(`${label}: failed to disable`)
        }
      }
    }
  }

  return Array.from(new Set(messages))
}

function resolveStatusMessage(result: unknown): string | null {
  if (!result || typeof result !== 'object') return null
  const data = result as DisableResult
  if (typeof data.message === 'string' && data.message.trim()) {
    return data.message
  }
  if (typeof data.status === 'string' && data.status.trim()) {
    return data.status
  }
  return null
}

export function PanelDisableDialog({ open, onOpenChange, panel }: PanelDisableDialogProps) {
  const disablePanelMutation = useDisablePanelMutation()
  const [errorSummary, setErrorSummary] = useState<string | null>(null)
  const [errorDetails, setErrorDetails] = useState<string[]>([])

  const handleClose = (state: boolean) => {
    if (!state) {
      setErrorSummary(null)
      setErrorDetails([])
    }
    onOpenChange(state)
  }

  const handleDisable = async () => {
    setErrorSummary(null)
    setErrorDetails([])

    try {
      const result = await disablePanelMutation.mutateAsync(panel.id)
      const remoteErrors = collectRemoteErrors(result)
      if (remoteErrors.length > 0) {
        setErrorSummary('Remote cleanup reported issues while disabling this panel:')
        setErrorDetails(remoteErrors)
        toast.error('Panel disabled with remote cleanup errors.')
        return
      }

      const statusMessage = resolveStatusMessage(result)
      toast.success(statusMessage ?? 'Panel disabled successfully.')
      handleClose(false)
    } catch (error) {
      let message = 'Failed to disable panel. Please try again.'
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string') {
          message = detail
        } else if (Array.isArray(detail)) {
          message = detail.join('\n')
        }
      }
      setErrorSummary(message)
      toast.error(message)
    }
  }

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={handleClose}
      handleConfirm={handleDisable}
      isLoading={disablePanelMutation.isPending}
      confirmText='Disable'
      title={
        <span className='inline-flex items-center gap-2'>
          <ShieldOff size={18} /> Disable panel
        </span>
      }
      desc={
        <div className='space-y-3'>
          <p>
            The panel <span className='font-semibold'>{panel.name}</span> will be disabled for new
            provisioning. Agents will no longer be able to sync against it until it is manually
            re-enabled via the API.
          </p>
          {(errorSummary || errorDetails.length > 0) && (
            <Alert variant='destructive'>
              <AlertTitle>{errorSummary ?? 'Remote cleanup failed'}</AlertTitle>
              <AlertDescription>
                <ul className='list-disc space-y-1 ps-4'>
                  {errorDetails.length > 0 ? (
                    errorDetails.map((item) => (
                      <li key={item} className='whitespace-pre-line'>
                        {item}
                      </li>
                    ))
                  ) : (
                    <li className='whitespace-pre-line'>{errorSummary}</li>
                  )}
                </ul>
              </AlertDescription>
            </Alert>
          )}
        </div>
      }
    />
  )
}
