import { useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  BadgeCheck,
  Bell,
  ChevronsUpDown,
  Copy,
  CreditCard,
  LogOut,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth-store'
import { rotateToken } from '@/services/auth-service'
import useDialogState from '@/hooks/use-dialog-state'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar'
import { SignOutDialog } from '@/components/sign-out-dialog'

type NavUserProps = {
  user: {
    name: string
    email: string
    avatar: string
  }
}

export function NavUser({ user }: NavUserProps) {
  const { isMobile } = useSidebar()
  const identity = useAuthStore((state) => state.identity)
  const updateToken = useAuthStore((state) => state.updateToken)
  const [open, setOpen] = useDialogState()

  const formatRole = useCallback(() => {
    if (!identity) return 'Guest'
    if (identity.role === 'agent' && identity.agent_name) {
      return identity.agent_name
    }
    return identity.role.replace('_', ' ')
  }, [identity])

  const roleSummary = identity ? identity.role.replace('_', ' ') : user.email
  const canRotateToken = identity?.role === 'agent' || identity?.role === 'super_admin'

  const rotateMutation = useMutation({
    mutationFn: async () => {
      if (!identity) {
        throw new Error('No authenticated identity')
      }
      return rotateToken(identity.role)
    },
    onSuccess: (newToken) => {
      updateToken(newToken)
      toast.success('API token rotated', {
        description: <TokenToast token={newToken} />,
        duration: 10000,
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

  const handleRotateToken = () => {
    if (!canRotateToken) {
      toast.error('Token rotation is only available for agents or super admins.')
      return
    }
    rotateMutation.mutate()
  }

  return (
    <>
      <SidebarMenu>
        <SidebarMenuItem>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <SidebarMenuButton
                size='lg'
                className='data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground'
              >
                <Avatar className='h-8 w-8 rounded-lg'>
                  <AvatarImage src={user.avatar} alt={user.name} />
                  <AvatarFallback className='rounded-lg'>
                    {formatRole()
                      .split(' ')
                      .map((part) => part[0]?.toUpperCase())
                      .join('')
                      .slice(0, 2) || 'VA'}
                  </AvatarFallback>
                </Avatar>
                <div className='grid flex-1 text-start text-sm leading-tight'>
                  <span className='truncate font-semibold'>{formatRole()}</span>
                  <span className='truncate text-xs'>{roleSummary}</span>
                </div>
                <ChevronsUpDown className='ms-auto size-4' />
              </SidebarMenuButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              className='w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg'
              side={isMobile ? 'bottom' : 'right'}
              align='end'
              sideOffset={4}
            >
              <DropdownMenuLabel className='p-0 font-normal'>
                <div className='flex items-center gap-2 px-1 py-1.5 text-start text-sm'>
                  <Avatar className='h-8 w-8 rounded-lg'>
                    <AvatarImage src={user.avatar} alt={user.name} />
                    <AvatarFallback className='rounded-lg'>
                      {formatRole()
                        .split(' ')
                        .map((part) => part[0]?.toUpperCase())
                        .join('')
                        .slice(0, 2) || 'VA'}
                    </AvatarFallback>
                  </Avatar>
                  <div className='grid flex-1 text-start text-sm leading-tight'>
                    <span className='truncate font-semibold'>{formatRole()}</span>
                    <span className='truncate text-xs'>{roleSummary}</span>
                  </div>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuItem>
                  <Sparkles />
                  Upgrade to Pro
                </DropdownMenuItem>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuItem asChild>
                  <Link to='/settings/account'>
                    <BadgeCheck />
                    Account
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link to='/settings'>
                    <CreditCard />
                    Billing
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link to='/settings/notifications'>
                    <Bell />
                    Notifications
                  </Link>
                </DropdownMenuItem>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={handleRotateToken}
                disabled={!identity || rotateMutation.isPending || !canRotateToken}
              >
                <RefreshCw className={rotateMutation.isPending ? 'animate-spin' : undefined} />
                Rotate token
              </DropdownMenuItem>
              <DropdownMenuItem
                variant='destructive'
                onClick={() => setOpen(true)}
              >
                <LogOut />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>

      <SignOutDialog open={!!open} onOpenChange={setOpen} />
    </>
  )
}

function TokenToast({ token }: { token: string }) {
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(token)
      toast.success('Token copied to clipboard', { duration: 2000 })
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Clipboard copy failed. Try manually copying.'
      toast.error(message)
    }
  }

  return (
    <div className='space-y-2'>
      <p className='break-all font-mono text-xs'>{token}</p>
      <Button size='sm' variant='outline' className='gap-2' onClick={handleCopy}>
        <Copy className='h-3 w-3' />
        Copy to clipboard
      </Button>
    </div>
  )
}
