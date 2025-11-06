import { type ColumnDef } from '@tanstack/react-table'
import { format } from 'date-fns'
import { Badge } from '@/components/ui/badge'
import { DataTableColumnHeader } from '@/components/data-table'
import type { Service } from '@/lib/api/types'
import { ServicesRowActions } from './services-row-actions'

export const servicesColumns: ColumnDef<Service>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Name' />,
    cell: ({ row }) => {
      const service = row.original
      return <span className='font-medium text-sm'>{service.name}</span>
    },
  },
  {
    id: 'metrics',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Metrics' />,
    enableSorting: false,
    cell: ({ row }) => {
      const service = row.original
      return (
        <div className='flex flex-wrap gap-2'>
          <Badge variant='secondary' className='font-mono text-xs'>
            Panels: {service.panel_count.toLocaleString()}
          </Badge>
          <Badge variant='outline' className='font-mono text-xs'>
            Users: {service.user_count.toLocaleString()}
          </Badge>
        </div>
      )
    },
  },
  {
    accessorKey: 'created_at',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Created' />,
    cell: ({ row }) => {
      const value = row.getValue<string>('created_at')
      try {
        const formatted = format(new Date(value), 'PP p')
        return (
          <time dateTime={value} className='text-sm text-muted-foreground'>
            {formatted}
          </time>
        )
      } catch {
        return <span className='text-muted-foreground'>{value}</span>
      }
    },
  },
  {
    id: 'actions',
    cell: ({ row }) => <ServicesRowActions service={row.original} />,
    enableSorting: false,
    enableHiding: false,
    size: 64,
  },
]
