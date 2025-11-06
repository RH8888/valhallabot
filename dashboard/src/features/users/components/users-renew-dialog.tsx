import { useEffect } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
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
import { useUpdateUserMutation } from '@/lib/api/users'
import { type User } from '@/lib/api/types'

const renewSchema = z.object({
  days: z.coerce
    .number({ invalid_type_error: 'Please enter a number of days.' })
    .int()
    .min(1, 'Renewal must be at least one day.'),
})

type RenewFormValues = z.infer<typeof renewSchema>

type UsersRenewDialogProps = {
  user: User
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function UsersRenewDialog({ user, open, onOpenChange }: UsersRenewDialogProps) {
  const form = useForm<RenewFormValues>({
    resolver: zodResolver(renewSchema),
    defaultValues: { days: 1 },
  })
  const updateMutation = useUpdateUserMutation(user.username)

  useEffect(() => {
    if (!open) {
      form.reset({ days: 1 })
    }
  }, [open, form])

  const handleSubmit = (values: RenewFormValues) => {
    updateMutation.mutate(
      {
        renew_days: values.days,
      },
      {
        onSuccess: () => {
          form.reset({ days: 1 })
          onOpenChange(false)
        },
      }
    )
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          onOpenChange(false)
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Renew user access</DialogTitle>
          <DialogDescription>
            Extend <span className='font-semibold'>{user.username}</span>'s access by
            adding days to the current expiry.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className='space-y-4'>
            <FormField
              control={form.control}
              name='days'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Additional days</FormLabel>
                  <FormControl>
                    <Input type='number' min={1} step={1} {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type='submit' disabled={updateMutation.isPending}>
                {updateMutation.isPending ? 'Renewing…' : 'Renew access'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
