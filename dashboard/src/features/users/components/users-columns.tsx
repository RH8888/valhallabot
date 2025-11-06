import { type ColumnDef } from '@tanstack/react-table'
import { Badge } from '@/components/ui/badge'
import { LongText } from '@/components/long-text'
import { type User } from '@/lib/api/types'
import { DataTableRowActions } from './data-table-row-actions'

export type UserRow = User & {
  serviceName: string | null
}

function formatBytes(value: number): string {
  if (value === 0) return '0 B'
  if (!Number.isFinite(value)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const exponent = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1
  )
  const num = value / Math.pow(1024, exponent)
  const formatted = num >= 10 || exponent === 0 ? num.toFixed(0) : num.toFixed(1)
  return `${formatted} ${units[exponent]}`
}

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return '—'
  }
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export const usersColumns: ColumnDef<UserRow>[] = [
  {
    accessorKey: 'username',
    header: 'Username',
    cell: ({ row }) => (
      <span className='font-medium'>{row.getValue<string>('username')}</span>
    ),
  },
  {
    accessorKey: 'serviceName',
    header: 'Service',
    cell: ({ row }) => row.original.serviceName ?? '—',
  },
  {
    accessorKey: 'plan_limit_bytes',
    header: 'Plan limit',
    cell: ({ row }) =>
      row.original.plan_limit_bytes > 0
        ? formatBytes(row.original.plan_limit_bytes)
        : 'Unlimited',
  },
  {
    id: 'usage',
    header: 'Usage',
    cell: ({ row }) => {
      const used = row.original.used_bytes
      const limit = row.original.plan_limit_bytes
      if (limit <= 0) {
        return `${formatBytes(used)} used`
      }
      const pct = Math.min(100, (used / limit) * 100)
      return `${formatBytes(used)} of ${formatBytes(limit)} (${pct.toFixed(1)}%)`
    },
  },
  {
    accessorKey: 'expire_at',
    header: 'Expires',
    cell: ({ row }) => formatDateTime(row.original.expire_at),
  },
  {
    id: 'status',
    header: 'Status',
    cell: ({ row }) => (
      <Badge variant={row.original.disabled ? 'destructive' : 'secondary'}>
        {row.original.disabled ? 'Disabled' : 'Active'}
      </Badge>
    ),
  },
  {
    accessorKey: 'access_key',
    header: 'Access key',
    cell: ({ row }) =>
      row.original.access_key ? (
        <LongText className='max-w-40'>{row.original.access_key}</LongText>
      ) : (
        '—'
      ),
  },
  {
    accessorKey: 'key_expires_at',
    header: 'Key expires',
    cell: ({ row }) => formatDateTime(row.original.key_expires_at),
  },
  {
    id: 'actions',
    cell: DataTableRowActions,
  },
]
