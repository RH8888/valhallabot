import { DotsHorizontalIcon } from '@radix-ui/react-icons'
import { LayoutGrid, PenLine, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { Service } from '@/lib/api/types'
import { useServices } from './services-provider'

type ServicesRowActionsProps = {
  service: Service
}

export function ServicesRowActions({ service }: ServicesRowActionsProps) {
  const { setCurrentService, setOpen } = useServices()

  const handleOpen = (dialog: 'edit' | 'delete' | 'panels') => {
    setCurrentService(service)
    setOpen(dialog)
  }

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant='ghost'
          className='data-[state=open]:bg-muted flex h-8 w-8 p-0'
        >
          <DotsHorizontalIcon className='h-4 w-4' />
          <span className='sr-only'>Open menu</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end' className='w-48'>
        <DropdownMenuItem onClick={() => handleOpen('edit')}>
          Edit
          <DropdownMenuShortcut>
            <PenLine size={16} />
          </DropdownMenuShortcut>
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => handleOpen('panels')}>
          Manage panels
          <DropdownMenuShortcut>
            <LayoutGrid size={16} />
          </DropdownMenuShortcut>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={() => handleOpen('delete')}
          className='text-destructive focus:text-destructive'
        >
          Delete
          <DropdownMenuShortcut>
            <Trash2 size={16} />
          </DropdownMenuShortcut>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
