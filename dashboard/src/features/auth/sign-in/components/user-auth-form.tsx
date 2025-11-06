import { useMemo } from 'react'
import { z } from 'zod'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { LogIn } from 'lucide-react'
import { toast } from 'sonner'
import { AxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth-store'
import { fetchWhoAmI } from '@/services/auth-service'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { LoadingIndicator } from '@/components/ui/loading-indicator'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Textarea } from '@/components/ui/textarea'

const formSchema = z.object({
  token: z
    .string()
    .min(1, 'Enter an API token')
    .max(512, 'Tokens are limited to 512 characters'),
})

function resolveErrorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    if (error.response?.status === 401) {
      return 'The provided token is invalid or has expired. Please try again.'
    }
    if (error.response?.status === 403) {
      return 'This token is not authorized to access the console.'
    }
    const detail = (error.response?.data as { detail?: string } | undefined)?.detail
    return detail ?? error.message
  }

  if (error instanceof Error) return error.message
  return 'Unable to verify API token. Please try again.'
}

interface UserAuthFormProps extends React.HTMLAttributes<HTMLFormElement> {
  redirectTo?: string
}

export function UserAuthForm({
  className,
  redirectTo,
  ...props
}: UserAuthFormProps) {
  const navigate = useNavigate()
  const setSession = useAuthStore((state) => state.setSession)

  const form = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      token: '',
    },
  })

  const mutation = useMutation({
    mutationFn: async (values: z.infer<typeof formSchema>) => {
      const identity = await fetchWhoAmI(values.token.trim())
      return { identity, token: values.token.trim() }
    },
    onSuccess: ({ identity, token }) => {
      setSession(token, identity)

      const label = identity.role === 'agent' ? identity.agent_name ?? 'Agent' : identity.role
      toast.success(`Authenticated as ${label}`)

      const targetPath = redirectTo || '/_authenticated/'
      navigate({ to: targetPath, replace: true })
    },
    onError: (error: unknown) => {
      toast.error(resolveErrorMessage(error))
    },
  })

  const isLoading = mutation.isPending

  const errorMessage = useMemo(() => {
    const error = mutation.error
    if (!error) return null
    return resolveErrorMessage(error)
  }, [mutation.error])

  function onSubmit(values: z.infer<typeof formSchema>) {
    mutation.mutate(values)
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className={cn('grid gap-5', className)}
        {...props}
      >
        <FormField
          control={form.control}
          name='token'
          render={({ field }) => (
            <FormItem>
              <FormLabel>API token</FormLabel>
              <FormControl>
                <Textarea
                  placeholder='Paste an admin or agent API token'
                  rows={4}
                  className='resize-y'
                  {...field}
                />
              </FormControl>
              <FormDescription>
                Tokens are validated against the Valhalla API and stored securely in your
                browser for future requests.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        {errorMessage ? (
          <p className='text-destructive text-sm font-medium'>{errorMessage}</p>
        ) : null}

        <Button className='mt-2' disabled={isLoading}>
          {isLoading ? (
            <LoadingIndicator
              inline
              label=''
              size={18}
              className='text-primary-foreground'
            />
          ) : (
            <LogIn />
          )}
          Authenticate
        </Button>

        <div className='text-muted-foreground text-center text-sm'>
          Need help finding a token? Ask a Valhalla administrator to generate one for you.
        </div>
      </form>
    </Form>
  )
}
