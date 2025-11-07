import { useEffect, useMemo } from 'react'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { isAxiosError } from 'axios'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
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
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { JsonPreview } from './json-preview'
import { useSettingQuery, useUpsertSettingMutation } from '@/lib/api/settings'
import type { Setting } from '@/lib/api/types'
import type { SettingMetadata } from '../settings-metadata'

const baseValueSchema = z.string().trim().min(1, 'Value is required.')

const numberValueSchema = baseValueSchema.refine(
  (value) => !Number.isNaN(Number(value)),
  {
    message: 'Enter a valid number.',
  }
)

const jsonValueSchema = baseValueSchema.superRefine((value, ctx) => {
  try {
    JSON.parse(value)
  } catch (_error) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'Value must be valid JSON.' })
  }
})

const formSchemas = {
  string: z.object({ value: baseValueSchema }),
  number: z.object({ value: numberValueSchema }),
  json: z.object({ value: jsonValueSchema }),
}

type SettingFormValues = z.infer<(typeof formSchemas)[keyof typeof formSchemas]>

type SettingEditDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  setting: Setting | null
  metadata: SettingMetadata | null
}

function isJsonValid(value: string) {
  try {
    JSON.parse(value)
    return true
  } catch (_error) {
    return false
  }
}

export function SettingEditDialog({ open, onOpenChange, setting, metadata }: SettingEditDialogProps) {
  const key = setting?.key ?? ''
  const type = metadata?.type ?? 'string'

  const schema = useMemo(() => formSchemas[type] ?? formSchemas.string, [type])
  const form = useForm<SettingFormValues>({
    resolver: zodResolver(schema),
    defaultValues: { value: setting?.value ?? '' },
  })

  const { data, isPending, isError, error } = useSettingQuery(key, open && !!key)
  const upsertSetting = useUpsertSettingMutation(key)

  const currentValue = data?.value ?? setting?.value ?? ''

  useEffect(() => {
    if (open) {
      form.reset({ value: currentValue ?? '' })
    }
  }, [open, currentValue, form])

  const handleClose = (state: boolean) => {
    if (!state) {
      form.reset({ value: currentValue ?? '' })
    }
    onOpenChange(state)
  }

  const onSubmit = async (values: SettingFormValues) => {
    const rawValue = typeof values.value === 'string' ? values.value.trim() : String(values.value)
    try {
      await upsertSetting.mutateAsync({ value: rawValue })
      handleClose(false)
    } catch (err) {
      let message = 'Unexpected error while saving the setting.'
      if (isAxiosError(err)) {
        const detail = err.response?.data?.detail
        if (typeof detail === 'string') {
          message = detail
        } else if (Array.isArray(detail) && detail.length > 0) {
          message = detail.join('\n')
        }
      }
      toast.error(message)
    }
  }

  const watchedValue = form.watch('value') ?? ''
  const jsonValid = metadata?.type === 'json' ? isJsonValid(watchedValue) : false

  let loadError: string | null = null
  if (isError) {
    if (isAxiosError(error)) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') {
        loadError = detail
      } else if (Array.isArray(detail) && detail.length > 0) {
        loadError = detail.join('\n')
      } else {
        loadError = error.message
      }
    } else if (error instanceof Error) {
      loadError = error.message
    } else {
      loadError = 'Unable to load the latest value.'
    }
  }

  const mutationPending = upsertSetting.isPending

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className='sm:max-w-xl'>
        <DialogHeader>
          <DialogTitle>Edit {metadata?.label ?? setting?.key}</DialogTitle>
          <DialogDescription>
            {metadata?.description ?? 'Update the configuration value for this setting.'}
          </DialogDescription>
        </DialogHeader>

        {metadata && (
          <div className='flex flex-wrap items-center gap-2 text-sm'>
            <Badge variant='secondary'>{metadata.type === 'json' ? 'JSON' : metadata.type === 'number' ? 'Numeric' : 'Text'}</Badge>
            <span className='font-mono text-xs text-muted-foreground'>Key: {metadata.key}</span>
            {metadata.critical && (
              <Badge variant='destructive'>Critical control</Badge>
            )}
          </div>
        )}

        {loadError && (
          <Alert variant='destructive'>
            <AlertTitle>Unable to refresh setting</AlertTitle>
            <AlertDescription className='whitespace-pre-wrap'>{loadError}</AlertDescription>
          </Alert>
        )}

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className='space-y-6'>
            <FormField
              control={form.control}
              name='value'
              render={({ field }) => (
                <FormItem className='space-y-3'>
                  <FormLabel>Value</FormLabel>
                  <FormControl>
                    {metadata?.type === 'json' ? (
                      <Textarea
                        {...field}
                        rows={10}
                        placeholder='{"enabled": true}'
                        className='font-mono'
                      />
                    ) : (
                      <Input
                        {...field}
                        type={metadata?.type === 'number' ? 'number' : 'text'}
                        inputMode={metadata?.type === 'number' ? 'decimal' : undefined}
                        autoComplete='off'
                      />
                    )}
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {metadata?.type === 'json' && (
              <div className='space-y-2'>
                <Label className='text-sm font-medium'>Preview</Label>
                <JsonPreview value={watchedValue} isValid={jsonValid} />
              </div>
            )}

            <DialogFooter>
              <Button type='button' variant='outline' onClick={() => handleClose(false)} disabled={mutationPending}>
                Cancel
              </Button>
              <Button type='submit' disabled={mutationPending || isPending}>
                {mutationPending ? 'Saving…' : 'Save changes'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
