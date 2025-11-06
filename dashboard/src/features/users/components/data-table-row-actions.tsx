import { useState } from 'react'
import { DotsHorizontalIcon } from '@radix-ui/react-icons'
import { type Row } from '@tanstack/react-table'
import {
  CalendarPlus,
  CheckCircle2,
  Edit,
  Power,
  RotateCcw,
} from 'lucide-react'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  useToggleUserMutation,
  useUpdateUserMutation,
} from '@/lib/api/users'
import { type UserRow } from './users-columns'
import { useUsers } from './users-provider'

type DataTableRowActionsProps = {
  row: Row<UserRow>
}

export function DataTableRowActions({ row }: DataTableRowActionsProps) {
  const { setOpen, setCurrentRow } = useUsers()
  const [resetDialogOpen, setResetDialogOpen] = useState(false)
  const [toggleDialogOpen, setToggleDialogOpen] = useState(false)
  const updateMutation = useUpdateUserMutation(row.original.username)
  const toggleMutation = useToggleUserMutation()

  const isDisabled = row.original.disabled

  return (
    <>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button variant='ghost' className='data-[state=open]:bg-muted flex h-8 w-8 p-0'>
            <DotsHorizontalIcon className='h-4 w-4' />
            <span className='sr-only'>Open menu</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end' className='w-48'>
          <DropdownMenuItem
            onClick={() => {
              setCurrentRow(row.original)
              setOpen('edit')
            }}
          >
            <Edit className='me-2 h-4 w-4' /> Edit user
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setResetDialogOpen(true)}>
            <RotateCcw className='me-2 h-4 w-4' /> Reset usage
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => {
              setCurrentRow(row.original)
              setOpen('renew')
            }}
          >
            <CalendarPlus className='me-2 h-4 w-4' /> Renew access
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setToggleDialogOpen(true)}>
            {isDisabled ? (
              <CheckCircle2 className='me-2 h-4 w-4 text-emerald-500' />
            ) : (
              <Power className='me-2 h-4 w-4 text-destructive' />
            )}
            {isDisabled ? 'Enable user' : 'Disable user'}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <AlertDialog open={resetDialogOpen} onOpenChange={setResetDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reset usage for {row.original.username}?</AlertDialogTitle>
            <AlertDialogDescription>
              This will clear the tracked traffic usage so the user can start fresh
              against their current quota.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={updateMutation.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={updateMutation.isPending}
              onClick={() => {
                updateMutation.mutate(
                  { reset_used: true },
                  {
                    onSuccess: () => setResetDialogOpen(false),
                  }
                )
              }}
            >
              Reset usage
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={toggleDialogOpen} onOpenChange={setToggleDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {isDisabled ? 'Enable user' : 'Disable user'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {isDisabled
                ? 'Re-enable access so this user can authenticate again.'
                : 'Disable access to prevent this user from connecting to services.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={toggleMutation.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={toggleMutation.isPending}
              onClick={() => {
                toggleMutation.mutate(
                  { username: row.original.username, disable: !isDisabled },
                  {
                    onSuccess: () => setToggleDialogOpen(false),
                  }
                )
              }}
            >
              {isDisabled ? 'Enable user' : 'Disable user'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
