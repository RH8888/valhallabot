import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Copy, KeyRound, Loader2, RefreshCcw } from 'lucide-react'
import { toast } from 'sonner'
import type { Agent } from '@/lib/api/types'
import { fetchAgentToken, rotateAgentToken } from '@/lib/api/agents'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

type AgentTokenDialogProps = {
  agent: Agent
}

export function AgentTokenDialog({ agent }: AgentTokenDialogProps) {
  const [open, setOpen] = useState(false)
  const [token, setToken] = useState<string | null>(null)

  const viewMutation = useMutation({
    mutationFn: () => fetchAgentToken(agent.id),
    onSuccess: (fetched) => {
      setToken(fetched)
    },
    onError: (error: unknown) => {
      const message =
        error instanceof Error
          ? error.message
          : 'Unable to fetch the token. Please try again.'
      toast.error(message)
    },
  })

  const rotateMutation = useMutation({
    mutationFn: () => rotateAgentToken(agent.id),
    onSuccess: (freshToken) => {
      setToken(freshToken)
      toast.success('Token rotated', {
        description: 'Copy the new credential before closing this dialog.',
      })
    },
    onError: (error: unknown) => {
      const message =
        error instanceof Error
          ? error.message
          : 'Unable to rotate the token. Please try again.'
      toast.error(message)
    },
  })

  const isLoading = viewMutation.isPending || rotateMutation.isPending

  const handleCopy = async () => {
    if (!token) {
      toast.error('No token available to copy')
      return
    }
    try {
      await navigator.clipboard.writeText(token)
      toast.success('Copied to clipboard')
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : 'Clipboard copy failed. Try again from a secure environment.'
      toast.error(message)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant='outline' size='sm' className='gap-2'>
          <KeyRound className='h-4 w-4' />
          Token
        </Button>
      </DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2'>
            Agent credential
            <Badge variant='secondary' className='uppercase'>#{agent.id}</Badge>
          </DialogTitle>
          <DialogDescription>
            View or rotate the API token for <strong>{agent.name}</strong>. Tokens
            are shown once—copy them to your secure vault before closing.
          </DialogDescription>
        </DialogHeader>

        <div className='space-y-4 py-2'>
          <div className='rounded-md border bg-muted/40 p-3 text-sm'>
            <p className='font-medium text-muted-foreground'>Telegram ID</p>
            <p className='font-mono text-sm'>{agent.telegram_user_id}</p>
          </div>

          <div className='space-y-2'>
            <div className='flex flex-wrap items-center gap-2'>
              <Button
                size='sm'
                variant='secondary'
                onClick={() => viewMutation.mutate()}
                disabled={isLoading}
                className='gap-2'
              >
                {viewMutation.isPending ? (
                  <Loader2 className='h-4 w-4 animate-spin' />
                ) : (
                  <KeyRound className='h-4 w-4' />
                )}
                Reveal current token
              </Button>
              <Button
                size='sm'
                onClick={() => rotateMutation.mutate()}
                disabled={isLoading}
                className='gap-2'
              >
                {rotateMutation.isPending ? (
                  <Loader2 className='h-4 w-4 animate-spin' />
                ) : (
                  <RefreshCcw className='h-4 w-4' />
                )}
                Rotate token
              </Button>
            </div>
            {token ? (
              <div className='space-y-2 rounded-md border bg-muted/40 p-3'>
                <p className='text-xs font-medium uppercase text-muted-foreground'>
                  Freshly issued token
                </p>
                <div className='flex flex-wrap items-center gap-2'>
                  <code className='break-all font-mono text-sm'>{token}</code>
                  <Button variant='ghost' size='icon' onClick={handleCopy}>
                    <Copy className='h-4 w-4' />
                    <span className='sr-only'>Copy token</span>
                  </Button>
                </div>
                <p className='text-xs text-muted-foreground'>
                  Store this value securely—Valhalla will not display it again after the dialog closes.
                </p>
              </div>
            ) : (
              <p className='text-xs text-muted-foreground'>
                Use the actions above to fetch or rotate the agent token. A new token immediately replaces the previous one.
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant='ghost' onClick={() => setOpen(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
