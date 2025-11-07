import { useEffect } from 'react'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { isAxiosError } from 'axios'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  useCreateServiceMutation,
  useUpdateServiceMutation,
} from '@/lib/api/services'
import type { Service } from '@/lib/api/types'

type ServiceFormDialogProps = {
  mode: 'create' | 'edit'
  open: boolean
  onOpenChange: (open: boolean) => void
  service?: Service | null
}

const serviceFormSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, 'Name is required.')
    .max(128, 'Name must be 128 characters or fewer.'),
})

type ServiceFormValues = z.infer<typeof serviceFormSchema>

export function ServiceFormDialog({ mode, open, onOpenChange, service }: ServiceFormDialogProps) {
  const isEdit = mode === 'edit' && !!service
  const createService = useCreateServiceMutation()
  const updateService = useUpdateServiceMutation(service?.id ?? 0)

  const form = useForm<ServiceFormValues>({
    resolver: zodResolver(serviceFormSchema),
    defaultValues: {
      name: service?.name ?? '',
    },
  })

  useEffect(() => {
    if (open) {
      form.reset({
        name: service?.name ?? '',
      })
    }
  }, [open, service, form])

  const handleClose = (state: boolean) => {
    if (!state) {
      form.reset({
        name: service?.name ?? '',
      })
    }
    onOpenChange(state)
  }

  const onSubmit = async (values: ServiceFormValues) => {
    const payload = { name: values.name.trim() }
    try {
      if (isEdit && service) {
        await updateService.mutateAsync(payload)
      } else {
        await createService.mutateAsync(payload)
      }
      handleClose(false)
    } catch (error) {
      let message = 'Unexpected error occurred while saving the service.'
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string') {
          message = detail
          form.setError('name', { type: 'server', message })
        } else if (Array.isArray(detail) && detail.length > 0) {
          message = detail.join('\n')
        }
      }
      toast.error(message)
    }
  }

  const mutationPending = createService.isPending || updateService.isPending
  const title = isEdit ? 'Edit service' : 'Create service'
  const description = isEdit
    ? 'Rename this service. Existing assignments will be preserved.'
    : 'Create a named service to group panels and local users.'

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className='space-y-4'>
            <FormField
              control={form.control}
              name='name'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input autoFocus placeholder='Premium tier' autoComplete='off' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type='button' variant='outline' onClick={() => handleClose(false)}>
                Cancel
              </Button>
              <Button type='submit' disabled={mutationPending}>
                {isEdit ? 'Save changes' : 'Create service'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
