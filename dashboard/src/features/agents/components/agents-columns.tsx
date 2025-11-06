import { type ColumnDef } from '@tanstack/react-table'
import { formatDistanceToNow, parseISO } from 'date-fns'
import type { Agent } from '@/lib/api/types'
import { DataTableColumnHeader } from '@/components/data-table'
import { AgentStatusBadge } from './agent-status-badge'
import { InlineNumberEditor } from './inline-number-editor'
import { InlineDateEditor } from './inline-date-editor'
import { AgentTokenDialog } from './agent-token-dialog'
import { useUpdateAgentMutation } from '@/lib/api/agents'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '0 B'
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let index = 0
  let current = value
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024
    index += 1
  }
  const precision = index === 0 ? 0 : 2
  return `${current.toFixed(precision)} ${units[index]}`
}

function AgentNameCell({ agent }: { agent: Agent }) {
  const createdLabel = formatDistanceToNow(parseISO(agent.created_at), {
    addSuffix: true,
  })

  return (
    <div className='space-y-1'>
      <div className='flex items-center gap-2'>
        <span className='font-semibold'>{agent.name}</span>
        {!agent.active ? (
          <Badge variant='outline' className='border-destructive/40 text-destructive'>
            Suspended
          </Badge>
        ) : null}
      </div>
      <p className='text-xs text-muted-foreground'>
        Telegram: {agent.telegram_user_id} • Created {createdLabel}
      </p>
    </div>
  )
}

function AgentQuotaCell({ agent }: { agent: Agent }) {
  const mutation = useUpdateAgentMutation(agent.id)
  const helper = `Consumed ${formatBytes(agent.total_used_bytes)} so far`

  return (
    <InlineNumberEditor
      label='Plan quota'
      value={agent.plan_limit_bytes}
      helperText={helper}
      unit='bytes'
      formatValue={(value) => `${formatBytes(value)} (${value.toLocaleString()} B)`}
      onSave={async (next) => {
        const sanitized = Math.max(0, Math.floor(next))
        await mutation.mutateAsync({ plan_limit_bytes: sanitized })
      }}
      isSaving={mutation.isPending}
    />
  )
}

function AgentUserLimitCell({ agent }: { agent: Agent }) {
  const mutation = useUpdateAgentMutation(agent.id)

  return (
    <InlineNumberEditor
      label='User limit'
      value={agent.user_limit}
      helperText='Set to 0 for unlimited users.'
      onSave={async (next) => {
        const sanitized = Math.max(0, Math.floor(next))
        await mutation.mutateAsync({ user_limit: sanitized })
      }}
      isSaving={mutation.isPending}
    />
  )
}

function AgentPerUserQuotaCell({ agent }: { agent: Agent }) {
  const mutation = useUpdateAgentMutation(agent.id)

  return (
    <InlineNumberEditor
      label='Per-user quota'
      value={agent.max_user_bytes}
      helperText='0 disables the per-user cap.'
      unit='bytes'
      formatValue={(value) => `${formatBytes(value)} (${value.toLocaleString()} B)`}
      onSave={async (next) => {
        const sanitized = Math.max(0, Math.floor(next))
        await mutation.mutateAsync({ max_user_bytes: sanitized })
      }}
      isSaving={mutation.isPending}
    />
  )
}

function AgentExpiryCell({ agent }: { agent: Agent }) {
  const mutation = useUpdateAgentMutation(agent.id)

  return (
    <InlineDateEditor
      label='Expiry'
      value={agent.expire_at ?? null}
      onSave={async (next) => {
        await mutation.mutateAsync({ expire_at: next })
      }}
      isSaving={mutation.isPending}
    />
  )
}

function AgentUsageCell({ agent }: { agent: Agent }) {
  const limit = Math.max(0, agent.plan_limit_bytes)
  const used = Math.max(0, agent.total_used_bytes)
  const percent = limit > 0 ? Math.min(100, (used / limit) * 100) : 0

  return (
    <div className='space-y-2'>
      <div className='flex items-center justify-between text-xs font-medium uppercase text-muted-foreground'>
        <span>Used</span>
        <span>{limit > 0 ? `${percent.toFixed(1)}%` : 'Unlimited'}</span>
      </div>
      <div className='h-2 w-full overflow-hidden rounded-full bg-muted'>
        <div
          className='h-full bg-primary transition-all'
          style={{ width: `${limit > 0 ? percent : 100}%` }}
        />
      </div>
      <div className='text-sm font-medium leading-tight'>
        {formatBytes(used)}{' '}
        <span className='text-xs font-normal text-muted-foreground'>
          of {limit > 0 ? formatBytes(limit) : 'no quota cap'}
        </span>
      </div>
    </div>
  )
}

function AgentStatusCell({ agent }: { agent: Agent }) {
  const mutation = useUpdateAgentMutation(agent.id)

  return (
    <div className='space-y-2'>
      <div className='flex items-center gap-2'>
        <AgentStatusBadge active={agent.active} />
        <Switch
          checked={agent.active}
          onCheckedChange={(checked) => {
            mutation.mutate({ active: checked })
          }}
          disabled={mutation.isPending}
          aria-label={checkedLabel(agent.active)}
        />
      </div>
      <p className='text-xs text-muted-foreground'>
        {agent.active
          ? 'Disable to immediately suspend provisioning.'
          : 'Enable to restore provisioning for this agent.'}
      </p>
    </div>
  )
}

function checkedLabel(active: boolean) {
  return active ? 'Disable agent' : 'Enable agent'
}

function AgentTokenCell({ agent }: { agent: Agent }) {
  return (
    <div className='flex flex-wrap gap-2'>
      <AgentTokenDialog agent={agent} />
    </div>
  )
}

export const agentsColumns: ColumnDef<Agent>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Agent' />,
    cell: ({ row }) => <AgentNameCell agent={row.original} />,
    sortingFn: 'alphanumeric',
  },
  {
    accessorKey: 'plan_limit_bytes',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Quota' />,
    cell: ({ row }) => <AgentQuotaCell agent={row.original} />,
    enableSorting: true,
  },
  {
    accessorKey: 'total_used_bytes',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Usage' />,
    cell: ({ row }) => <AgentUsageCell agent={row.original} />,
    enableSorting: true,
  },
  {
    accessorKey: 'user_limit',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Users' />,
    cell: ({ row }) => <AgentUserLimitCell agent={row.original} />,
  },
  {
    accessorKey: 'max_user_bytes',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Per-user cap' />,
    cell: ({ row }) => <AgentPerUserQuotaCell agent={row.original} />,
  },
  {
    accessorKey: 'expire_at',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Expiry' />,
    cell: ({ row }) => <AgentExpiryCell agent={row.original} />,
    sortingFn: (rowA, rowB, id) => {
      const a = rowA.getValue<string | null>(id)
      const b = rowB.getValue<string | null>(id)
      if (!a && !b) return 0
      if (!a) return 1
      if (!b) return -1
      const timeA = Date.parse(a)
      const timeB = Date.parse(b)
      return timeA - timeB
    },
  },
  {
    accessorKey: 'active',
    header: ({ column }) => <DataTableColumnHeader column={column} title='Status' />,
    cell: ({ row }) => <AgentStatusCell agent={row.original} />,
    filterFn: (row, id, value) => {
      const status = row.getValue<boolean>(id) ? 'active' : 'inactive'
      return Array.isArray(value) ? value.includes(status) : true
    },
  },
  {
    id: 'actions',
    header: () => <span className='sr-only'>Actions</span>,
    cell: ({ row }) => <AgentTokenCell agent={row.original} />,
    enableSorting: false,
    enableHiding: false,
  },
]
