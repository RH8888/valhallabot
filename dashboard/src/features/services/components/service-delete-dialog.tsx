import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { isAxiosError } from 'axios'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ConfirmDialog } from '@/components/confirm-dialog'
import type { Service } from '@/lib/api/types'
import { useDeleteServiceMutation } from '@/lib/api/services'

type ServiceDeleteDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  service: Service
}

export function ServiceDeleteDialog({ open, onOpenChange, service }: ServiceDeleteDialogProps) {
  const deleteService = useDeleteServiceMutation()
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
      await deleteService.mutateAsync(service.id)
      handleClose(false)
    } catch (error) {
      let message = 'Failed to delete service. Please try again.'
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
      isLoading={deleteService.isPending}
      destructive
      confirmText='Delete'
      title={
        <span className='text-destructive inline-flex items-center gap-2'>
          <AlertTriangle size={18} /> Delete service
        </span>
      }
      desc={
        <div className='space-y-3'>
          <p>
            Removing <span className='font-semibold'>{service.name}</span> will detach all panel
            associations. Local users or agents linked to this service must be reassigned before
            deletion.
          </p>
          {errorMessage && (
            <Alert variant='destructive'>
              <AlertTitle>Unable to remove service</AlertTitle>
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
