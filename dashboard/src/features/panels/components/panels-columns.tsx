import { type ColumnDef } from '@tanstack/react-table'
import { format } from 'date-fns'
import { Link } from '@tanstack/react-router'
import { Badge } from '@/components/ui/badge'
import { DataTableColumnHeader } from '@/components/data-table'
import { LongText } from '@/components/long-text'
import type { Panel } from '@/lib/api/types'
import { PANEL_TYPES } from '../constants'
import { PanelRowActions } from './panels-row-actions'

const PANEL_TYPE_LOOKUP = new Map<string, string>(
  PANEL_TYPES.map((type) => [type.value, type.label])
)

export const panelsColumns: ColumnDef<Panel>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Name' />,
    cell: ({ row }) => {
      const panel = row.original
      return (
        <Link
          to='/panels/$panelId'
          params={{ panelId: panel.id.toString() }}
          className='font-medium text-primary underline-offset-4 hover:underline'
        >
          {panel.name}
        </Link>
      )
    },
  },
  {
    accessorKey: 'panel_type',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Type' />,
    cell: ({ row }) => {
      const value = row.getValue<string>('panel_type')
      const label = PANEL_TYPE_LOOKUP.get(value) ?? value
      return <Badge variant='outline'>{label}</Badge>
    },
    filterFn: (row, id, value) => {
      return Array.isArray(value) ? value.includes(row.getValue(id)) : true
    },
    enableHiding: false,
  },
  {
    accessorKey: 'panel_url',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Panel URL' />,
    cell: ({ row }) => {
      const url = row.getValue<string>('panel_url')
      return (
        <a
          href={url}
          target='_blank'
          rel='noreferrer'
          className='text-sm text-muted-foreground underline-offset-4 hover:underline'
        >
          <LongText className='max-w-[15rem]'>{url}</LongText>
        </a>
      )
    },
  },
  {
    accessorKey: 'template_username',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Template user' />,
    cell: ({ row }) => {
      const value = row.getValue<string | null>('template_username')
      return value ? (
        <LongText className='max-w-[10rem]'>{value}</LongText>
      ) : (
        <span className='text-muted-foreground'>—</span>
      )
    },
  },
  {
    accessorKey: 'sub_url',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Subscription link' />,
    cell: ({ row }) => {
      const subUrl = row.getValue<string | null>('sub_url')
      if (!subUrl) {
        return <span className='text-muted-foreground'>—</span>
      }
      return (
        <a
          href={subUrl}
          target='_blank'
          rel='noreferrer'
          className='text-sm text-muted-foreground underline-offset-4 hover:underline'
        >
          <LongText className='max-w-[15rem]'>{subUrl}</LongText>
        </a>
      )
    },
  },
  {
    accessorKey: 'created_at',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Created' />,
    cell: ({ row }) => {
      const value = row.getValue<string>('created_at')
      try {
        return (
          <time dateTime={value} className='text-sm text-muted-foreground'>
            {format(new Date(value), 'PP p')}
          </time>
        )
      } catch {
        return <span className='text-muted-foreground'>{value}</span>
      }
    },
  },
  {
    id: 'actions',
    cell: ({ row }) => <PanelRowActions panel={row.original} />, 
    size: 64,
    enableSorting: false,
    enableHiding: false,
  },
]
