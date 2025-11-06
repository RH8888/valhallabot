import { useEffect } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Button } from '@/components/ui/button'
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  useCreateUserMutation,
  useUpdateUserMutation,
} from '@/lib/api/users'
import { type User, type UserUpdate } from '@/lib/api/types'

export type ServiceOption = {
  label: string
  value: number
}

type BaseDrawerProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  services: ServiceOption[]
  isLoadingServices?: boolean
}

type CreateDrawerProps = BaseDrawerProps & {
  mode: 'create'
}

type EditDrawerProps = BaseDrawerProps & {
  mode: 'edit'
  user: User
}

type UserDrawerProps = CreateDrawerProps | EditDrawerProps

const createSchema = z.object({
  username: z
    .string({ required_error: 'Username is required.' })
    .trim()
    .min(1, 'Username is required.'),
  limitBytes: z.coerce
    .number({ invalid_type_error: 'Limit must be a number.' })
    .min(0, 'Limit cannot be negative.'),
  durationDays: z.coerce
    .number({ invalid_type_error: 'Duration must be a number.' })
    .min(0, 'Duration cannot be negative.'),
  serviceId: z.union([
    z.literal(''),
    z.coerce.number({ invalid_type_error: 'Invalid service.' }).int().positive(),
  ]),
})

type CreateFormValues = z.infer<typeof createSchema>

const editSchema = z.object({
  limitBytes: z.coerce
    .number({ invalid_type_error: 'Limit must be a number.' })
    .min(0, 'Limit cannot be negative.'),
  serviceId: z.union([
    z.literal(''),
    z.coerce.number({ invalid_type_error: 'Invalid service.' }).int().positive(),
  ]),
})

type EditFormValues = z.infer<typeof editSchema>

function CreateUserDrawer({
  open,
  onOpenChange,
  services,
  isLoadingServices,
}: CreateDrawerProps) {
  const createMutation = useCreateUserMutation()
  const form = useForm<CreateFormValues>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      username: '',
      limitBytes: 0,
      durationDays: 0,
      serviceId: '',
    },
  })

  const handleSubmit = (values: CreateFormValues) => {
    const payload = {
      username: values.username.trim(),
      limit_bytes: values.limitBytes,
      duration_days: values.durationDays,
      service_id: values.serviceId === '' ? null : Number(values.serviceId),
    }
    createMutation.mutate(payload, {
      onSuccess: () => {
        form.reset()
        onOpenChange(false)
      },
    })
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          form.reset()
          onOpenChange(false)
        }
      }}
    >
      <SheetContent className='w-full sm:max-w-lg'>
        <SheetHeader>
          <SheetTitle>Create user</SheetTitle>
          <SheetDescription>
            Provision a new user account with service access and usage quota.
          </SheetDescription>
        </SheetHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className='flex flex-1 flex-col gap-4 p-4'>
            <FormField
              control={form.control}
              name='username'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Username</FormLabel>
                  <FormControl>
                    <Input placeholder='customer001' autoComplete='off' {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className='grid gap-4 sm:grid-cols-2'>
              <FormField
                control={form.control}
                name='limitBytes'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Limit (bytes)</FormLabel>
                    <FormControl>
                      <Input type='number' min={0} step={1} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name='durationDays'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Duration (days)</FormLabel>
                    <FormControl>
                      <Input type='number' min={0} step={1} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <FormField
              control={form.control}
              name='serviceId'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Service assignment</FormLabel>
                  <Select
                    value={field.value}
                    onValueChange={field.onChange}
                    disabled={isLoadingServices}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder='Select service (optional)' />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value=''>Unassigned</SelectItem>
                      {services.map((service) => (
                        <SelectItem key={service.value} value={String(service.value)}>
                          {service.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <SheetFooter>
              <Button type='submit' disabled={createMutation.isPending}>
                {createMutation.isPending ? 'Creating…' : 'Create user'}
              </Button>
            </SheetFooter>
          </form>
        </Form>
      </SheetContent>
    </Sheet>
  )
}

function EditUserDrawer({
  open,
  onOpenChange,
  services,
  isLoadingServices,
  user,
}: EditDrawerProps) {
  const updateMutation = useUpdateUserMutation(user.username)
  const form = useForm<EditFormValues>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      limitBytes: user.plan_limit_bytes,
      serviceId: user.service_id ? String(user.service_id) : '',
    },
  })

  useEffect(() => {
    if (open) {
      form.reset({
        limitBytes: user.plan_limit_bytes,
        serviceId: user.service_id ? String(user.service_id) : '',
      })
    }
  }, [open, user, form])

  const handleSubmit = (values: EditFormValues) => {
    const payload: UserUpdate = {}
    if (values.limitBytes !== user.plan_limit_bytes) {
      payload.limit_bytes = values.limitBytes
    }
    if (values.serviceId === '') {
      if (user.service_id !== null) {
        payload.service_id = null
      }
    } else {
      const nextService = Number(values.serviceId)
      if (nextService !== user.service_id) {
        payload.service_id = nextService
      }
    }
    updateMutation.mutate(payload, {
      onSuccess: () => {
        form.reset({
          limitBytes: values.limitBytes,
          serviceId: values.serviceId,
        })
        onOpenChange(false)
      },
    })
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          form.reset({
            limitBytes: user.plan_limit_bytes,
            serviceId: user.service_id ? String(user.service_id) : '',
          })
          onOpenChange(false)
        }
      }}
    >
      <SheetContent className='w-full sm:max-w-lg'>
        <SheetHeader>
          <SheetTitle>Edit user</SheetTitle>
          <SheetDescription>
            Adjust quota limits and service assignments for this user.
          </SheetDescription>
        </SheetHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleSubmit)} className='flex flex-1 flex-col gap-4 p-4'>
            <div className='space-y-1'>
              <p className='text-sm font-medium text-muted-foreground'>Username</p>
              <p className='font-semibold'>{user.username}</p>
            </div>
            <div className='grid gap-4 sm:grid-cols-2'>
              <FormField
                control={form.control}
                name='limitBytes'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Limit (bytes)</FormLabel>
                    <FormControl>
                      <Input type='number' min={0} step={1} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <div className='space-y-1'>
                <p className='text-sm font-medium text-muted-foreground'>Current usage</p>
                <p>
                  {user.used_bytes.toLocaleString()} bytes used of{' '}
                  {user.plan_limit_bytes > 0
                    ? `${user.plan_limit_bytes.toLocaleString()} bytes`
                    : 'no quota limit'}
                </p>
              </div>
            </div>
            <FormField
              control={form.control}
              name='serviceId'
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Service assignment</FormLabel>
                  <Select
                    value={field.value}
                    onValueChange={field.onChange}
                    disabled={isLoadingServices}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder='Select service (optional)' />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value=''>Unassigned</SelectItem>
                      {services.map((service) => (
                        <SelectItem key={service.value} value={String(service.value)}>
                          {service.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <SheetFooter>
              <Button type='submit' disabled={updateMutation.isPending}>
                {updateMutation.isPending ? 'Saving…' : 'Save changes'}
              </Button>
            </SheetFooter>
          </form>
        </Form>
      </SheetContent>
    </Sheet>
  )
}

export function UsersActionDialog(props: UserDrawerProps) {
  if (props.mode === 'create') {
    return <CreateUserDrawer {...props} />
  }

  return <EditUserDrawer {...props} />
}
