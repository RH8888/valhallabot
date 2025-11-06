import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useLocation, useNavigate } from '@tanstack/react-router'
import { Copy, Eye, EyeOff, KeyRound, Loader2, RefreshCw, Shield } from 'lucide-react'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth-store'
import { rotateToken } from '@/services/auth-service'
import { useAgentTokenQuery, rotateMyAgentToken } from '@/lib/api/agents'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

function maskToken(token: string | null, revealed: boolean) {
  if (!token) return 'No token stored'
  if (revealed) return token
  if (token.length <= 8) return '••••••'
  return `${token.slice(0, 4)}••••${token.slice(-4)}`
}

export function TokenManager() {
  const [showToken, setShowToken] = useState(false)
  const [latestServerToken, setLatestServerToken] = useState<string | null>(null)
  const identity = useAuthStore((state) => state.identity)
  const token = useAuthStore((state) => state.token)
  const updateToken = useAuthStore((state) => state.updateToken)
  const clearSession = useAuthStore((state) => state.clearSession)
  const navigate = useNavigate()
  const location = useLocation()

  const canRotateToken = identity?.role === 'agent' || identity?.role === 'super_admin'

  const tokenQuery = useAgentTokenQuery(false)

  const rotateMutation = useMutation({
    mutationFn: async () => {
      if (!identity) throw new Error('No authenticated identity found')
      if (identity.role === 'agent') {
        return rotateMyAgentToken()
      }
      if (identity.role === 'super_admin') {
        return rotateToken(identity.role)
      }
      throw new Error('Token rotation requires agent or super admin privileges')
    },
    onSuccess: (newToken) => {
      updateToken(newToken)
      setLatestServerToken(newToken)
      toast.success('Token rotated', {
        description: 'Your new token is now used for authenticated requests.',
      })
    },
    onError: (error: unknown) => {
      const message =
        error instanceof Error
          ? error.message
          : 'Unable to rotate the token. Please try again later.'
      toast.error(message)
    },
  })

  const handleRevealFromServer = async () => {
    if (!identity || identity.role !== 'agent') {
      toast.error('Only agents can retrieve their token from the server.')
      return
    }
    try {
      const result = await tokenQuery.refetch()
      if (result.error) {
        throw result.error
      }
      if (result.data) {
        setLatestServerToken(result.data)
        toast.success('Token retrieved from server', {
          description: 'Copy it now—Valhalla only displays it on demand.',
        })
      }
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : 'Unable to fetch the token. Please try again later.'
      toast.error(message)
    }
  }

  const handleRotateToken = () => {
    if (!canRotateToken) {
      toast.error('Token rotation requires agent or super admin privileges.')
      return
    }
    rotateMutation.mutate()
  }

  const handleLogout = () => {
    clearSession()
    const redirect = location.href ?? `${location.pathname}${location.search ?? ''}`
    navigate({ to: '/sign-in', search: { redirect }, replace: true })
  }

  const handleCopy = async () => {
    const value = showToken ? token : latestServerToken ?? token
    if (!value) {
      toast.error('No token available to copy')
      return
    }

    try {
      await navigator.clipboard.writeText(value)
      toast.success('Token copied to clipboard')
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Clipboard copy failed. Try manually copying.'
      toast.error(message)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className='flex items-center gap-2 text-lg'>
          <Shield className='h-5 w-5' /> Session security
        </CardTitle>
        <CardDescription>
          Manage the credentials stored in your browser for Valhalla API access.
        </CardDescription>
      </CardHeader>
      <CardContent className='space-y-4'>
        <div className='space-y-1'>
          <p className='text-sm font-medium text-muted-foreground'>Signed in as</p>
          <div className='flex flex-wrap items-center gap-2'>
            <span className='font-semibold'>
              {identity?.agent_name ?? identity?.role.replace('_', ' ') ?? 'Guest'}
            </span>
            {identity ? (
              <Badge variant='outline' className='uppercase'>
                {identity.role.replace('_', ' ')}
              </Badge>
            ) : null}
          </div>
        </div>

        <div className='space-y-2'>
          <p className='text-sm font-medium text-muted-foreground'>Stored API token</p>
          <div className='flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm font-mono'>
            <span className='break-all'>{maskToken(token, showToken)}</span>
            <div className='ms-auto flex gap-2'>
              <Button
                size='icon'
                variant='ghost'
                onClick={() => setShowToken((prev) => !prev)}
                aria-label={showToken ? 'Hide token' : 'Reveal token'}
              >
                {showToken ? <EyeOff className='h-4 w-4' /> : <Eye className='h-4 w-4' />}
              </Button>
              <Button size='icon' variant='ghost' onClick={handleCopy} aria-label='Copy token'>
                <Copy className='h-4 w-4' />
              </Button>
            </div>
          </div>
          <p className='text-xs text-muted-foreground'>
            Tokens never leave your device except when calling the Valhalla API. Rotate them
            frequently to keep access secure.
          </p>
        </div>

        <div className='space-y-3 rounded-md border bg-muted/30 p-3'>
          <p className='text-sm font-medium text-muted-foreground'>
            Server-issued token
          </p>
          {latestServerToken ? (
            <div className='flex flex-wrap items-center gap-2 rounded border border-dashed bg-background px-3 py-2 text-sm font-mono'>
              <span className='break-all'>{latestServerToken}</span>
              <Button size='icon' variant='ghost' onClick={handleCopy} aria-label='Copy latest token'>
                <Copy className='h-4 w-4' />
              </Button>
            </div>
          ) : (
            <p className='text-xs text-muted-foreground'>
              Reveal or rotate the token to display it here. Valhalla will only show the raw value on demand.
            </p>
          )}
          <div className='flex flex-wrap gap-2'>
            <Button
              variant='secondary'
              size='sm'
              onClick={handleRevealFromServer}
              disabled={rotateMutation.isPending || tokenQuery.isFetching || identity?.role !== 'agent'}
              className='gap-2'
            >
              {tokenQuery.isFetching ? (
                <Loader2 className='h-4 w-4 animate-spin' />
              ) : (
                <KeyRound className='h-4 w-4' />
              )}
              Reveal from server
            </Button>
            <Button
              onClick={handleRotateToken}
              disabled={!canRotateToken || rotateMutation.isPending}
              variant='secondary'
              className={cn('gap-2', !canRotateToken && 'opacity-80')}
            >
              {rotateMutation.isPending ? (
                <Loader2 className='h-4 w-4 animate-spin' />
              ) : (
                <RefreshCw className='h-4 w-4' />
              )}
              Rotate token
            </Button>
          </div>
        </div>

        <div className='flex flex-wrap gap-2'>
          <Button onClick={handleLogout} variant='destructive'>
            Log out and clear token
          </Button>
        </div>

        {!canRotateToken && identity ? (
          <p className='text-xs text-muted-foreground'>
            Only agents and super admins can rotate tokens from this view. Contact an administrator
            if you need a new credential.
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}
