import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { isAxiosError } from 'axios'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ConfirmDialog } from '@/components/confirm-dialog'
import type { Panel } from '@/lib/api/types'
import { useDeletePanelMutation } from '@/lib/api/panels'

type PanelDeleteDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  panel: Panel
}

export function PanelDeleteDialog({ open, onOpenChange, panel }: PanelDeleteDialogProps) {
  const deletePanelMutation = useDeletePanelMutation()
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleClose = (state: boolean) => {
    if (!state) {
      setErrorMessage(null)
    }
    onOpenChange(state)
  }

  const handleDelete = async () => {
    setErrorMessage(null)
    try {
      await deletePanelMutation.mutateAsync(panel.id)
      handleClose(false)
    } catch (error) {
      let message = 'Failed to delete panel. Please try again.'
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string') {
          message = detail
        } else if (Array.isArray(detail)) {
          message = detail.join('\n')
        }
      }
      setErrorMessage(message)
      toast.error(message)
    }
  }

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={handleClose}
      handleConfirm={handleDelete}
      isLoading={deletePanelMutation.isPending}
      destructive
      confirmText='Delete'
      title={
        <span className='text-destructive inline-flex items-center gap-2'>
          <AlertTriangle size={18} /> Delete panel
        </span>
      }
      desc={
        <div className='space-y-3'>
          <p>
            Removing <span className='font-semibold'>{panel.name}</span> will unlink all
            associated local users. Any remote cleanup errors reported by the API will be
            shown below.
          </p>
          {errorMessage && (
            <Alert variant='destructive'>
              <AlertTitle>Unable to remove panel</AlertTitle>
              <AlertDescription className='whitespace-pre-line'>
                {errorMessage}
              </AlertDescription>
            </Alert>
          )}
        </div>
      }
    />
  )
}
