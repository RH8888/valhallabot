import { DotsHorizontalIcon } from '@radix-ui/react-icons'
import { Link } from '@tanstack/react-router'
import { Eye, PenLine, ShieldOff, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { Panel } from '@/lib/api/types'
import { usePanels } from './panels-provider'

type PanelRowActionsProps = {
  panel: Panel
}

export function PanelRowActions({ panel }: PanelRowActionsProps) {
  const { setCurrentPanel, setOpen } = usePanels()

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
        <DropdownMenuItem asChild>
          <Link to='/panels/$panelId' params={{ panelId: panel.id.toString() }}>
            View details
            <DropdownMenuShortcut>
              <Eye size={16} />
            </DropdownMenuShortcut>
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={() => {
            setCurrentPanel(panel)
            setOpen('edit')
          }}
        >
          Edit
          <DropdownMenuShortcut>
            <PenLine size={16} />
          </DropdownMenuShortcut>
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => {
            setCurrentPanel(panel)
            setOpen('disable')
          }}
        >
          Disable
          <DropdownMenuShortcut>
            <ShieldOff size={16} />
          </DropdownMenuShortcut>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={() => {
            setCurrentPanel(panel)
            setOpen('delete')
          }}
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
