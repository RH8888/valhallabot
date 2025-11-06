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
import { PasswordInput } from '@/components/password-input'
import { SelectDropdown } from '@/components/select-dropdown'
import { PANEL_TYPES, type PanelTypeValue } from '../constants'
import { useCreatePanelMutation, useUpdatePanelMutation } from '@/lib/api/panels'
import type { Panel } from '@/lib/api/types'

type PanelFormDialogProps = {
  mode: 'create' | 'edit'
  open: boolean
  onOpenChange: (open: boolean) => void
  panel?: Panel | null
}

const optionalStringSchema = z
  .string()
  .optional()
  .transform((value) => value?.trim() ?? '')

const optionalUrlSchema = z
  .string()
  .optional()
  .transform((value) => value?.trim() ?? '')
  .refine((value) => {
    if (!value) return true
    try {
      new URL(value)
      return true
    } catch {
      return false
    }
  }, {
    message: 'Must be a valid URL including the protocol.',
  })

type OptionalString = z.infer<typeof optionalStringSchema>
type OptionalUrl = z.infer<typeof optionalUrlSchema>

const panelFormSchema = z.object({
  name: z.string().min(1, 'Name is required.'),
  panel_url: z
    .string()
    .trim()
    .url('Please enter a valid URL including the protocol.'),
  panel_type: z.custom<PanelTypeValue>((value) =>
    PANEL_TYPES.some((type) => type.value === value)
  , {
    message: 'Panel type is required.',
  }),
  admin_username: z.string().min(1, 'Admin username is required.'),
  access_token: z.string().min(1, 'Access token is required.'),
  template_username: optionalStringSchema,
  sub_url: optionalUrlSchema,
})

function resolveOptionalField(value?: OptionalString | OptionalUrl) {
  if (!value) return null
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

type PanelFormValues = z.infer<typeof panelFormSchema>

export function PanelFormDialog({ mode, open, onOpenChange, panel }: PanelFormDialogProps) {
  const isEdit = mode === 'edit' && !!panel
  const createPanel = useCreatePanelMutation()
  const updatePanel = useUpdatePanelMutation(panel?.id)

  const form = useForm<PanelFormValues>({
    resolver: zodResolver(panelFormSchema),
    defaultValues: {
      name: panel?.name ?? '',
      panel_url: panel?.panel_url ?? '',
      panel_type: (panel?.panel_type as PanelTypeValue | undefined) ?? 'marzneshin',
      admin_username: panel?.admin_username ?? '',
      access_token: panel?.access_token ?? '',
      template_username: panel?.template_username ?? '',
      sub_url: panel?.sub_url ?? '',
    },
  })

  useEffect(() => {
    if (open) {
      form.reset({
        name: panel?.name ?? '',
        panel_url: panel?.panel_url ?? '',
        panel_type: (panel?.panel_type as PanelTypeValue | undefined) ?? 'marzneshin',
        admin_username: panel?.admin_username ?? '',
        access_token: panel?.access_token ?? '',
        template_username: panel?.template_username ?? '',
        sub_url: panel?.sub_url ?? '',
      })
    }
  }, [open, panel, form])

  const onSubmit = async (values: PanelFormValues) => {
    const payload = {
      name: values.name.trim(),
      panel_url: values.panel_url.trim(),
      panel_type: values.panel_type,
      admin_username: values.admin_username.trim(),
      access_token: values.access_token.trim(),
      template_username: resolveOptionalField(values.template_username),
      sub_url: resolveOptionalField(values.sub_url),
    }

    try {
      if (isEdit && panel) {
        await updatePanel.mutateAsync(payload)
      } else {
        await createPanel.mutateAsync(payload)
      }
      onOpenChange(false)
    } catch (error) {
      let message = 'Unexpected error occurred while saving the panel.'
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string') {
          message = detail
        } else if (detail && typeof detail === 'object') {
          message = 'Failed to save panel. Please review the provided values.'
        }
      }
      toast.error(message)
    }
  }

  const mutationPending =
    createPanel.isPending || updatePanel.isPending

  const title = isEdit ? 'Edit panel' : 'Create panel'
  const description = isEdit
    ? 'Update the connection details for this panel.'
    : 'Register a new panel to make it available to agents.'

  return (
    <Dialog
      open={open}
      onOpenChange={(state) => {
        if (!state) {
          form.reset()
        }
        onOpenChange(state)
      }}
    >
      <DialogContent className='sm:max-w-xl'>
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
                    <Input placeholder='Primary panel' autoComplete='off' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='panel_url'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Panel URL</FormLabel>
                  <FormControl>
                    <Input placeholder='https://panel.example.com' type='url' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='panel_type'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Panel type</FormLabel>
                  <SelectDropdown
                    defaultValue={field.value}
                    onValueChange={field.onChange}
                    placeholder='Select a panel type'
                    items={PANEL_TYPES.map((item) => ({
                      label: item.label,
                      value: item.value,
                    }))}
                  />
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='admin_username'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Administrator username</FormLabel>
                  <FormControl>
                    <Input placeholder='admin' autoComplete='off' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='access_token'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Access token</FormLabel>
                  <FormControl>
                    <PasswordInput placeholder='Paste the API token' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='template_username'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Template username</FormLabel>
                  <FormControl>
                    <Input placeholder='Optional template user' autoComplete='off' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name='sub_url'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Subscription URL</FormLabel>
                  <FormControl>
                    <Input placeholder='https://panel.example.com/sub' type='url' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type='button' variant='outline' onClick={() => onOpenChange(false)} disabled={mutationPending}>
                Cancel
              </Button>
              <Button type='submit' disabled={mutationPending}>
                {mutationPending ? 'Saving…' : 'Save panel'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
