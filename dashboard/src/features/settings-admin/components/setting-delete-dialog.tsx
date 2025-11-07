import { isAxiosError } from 'axios'
import { toast } from 'sonner'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { useDeleteSettingMutation } from '@/lib/api/settings'
import type { Setting } from '@/lib/api/types'
import type { SettingMetadata } from '../settings-metadata'

type SettingDeleteDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  setting: Setting | null
  metadata: SettingMetadata | null
}

export function SettingDeleteDialog({ open, onOpenChange, setting, metadata }: SettingDeleteDialogProps) {
  const deleteSetting = useDeleteSettingMutation()

  const handleConfirm = async () => {
    if (!setting) return
    try {
      await deleteSetting.mutateAsync(setting.key)
      onOpenChange(false)
    } catch (error) {
      let message = 'Unexpected error while deleting the setting.'
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string') {
          message = detail
        } else if (Array.isArray(detail) && detail.length > 0) {
          message = detail.join('\n')
        }
      }
      toast.error(message)
    }
  }

  const label = metadata?.label ?? setting?.key ?? 'this setting'

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Delete ${label}`}
      desc={`Deleting this entry removes the ${label.toLowerCase()} override. This action cannot be undone.`}
      destructive
      confirmText={deleteSetting.isPending ? 'Deleting…' : 'Delete'}
      handleConfirm={handleConfirm}
      isLoading={deleteSetting.isPending}
    >
      <p className='text-sm text-muted-foreground'>
        Key: <span className='font-mono text-xs'>{setting?.key}</span>
      </p>
    </ConfirmDialog>
  )
}
