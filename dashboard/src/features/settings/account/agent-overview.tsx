import { formatDistanceToNow, parseISO } from 'date-fns'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { AgentStatusBadge } from '@/features/agents/components/agent-status-badge'
import { useAgentProfileQuery } from '@/lib/api/agents'
import type { AgentProfile } from '@/lib/api/types'

function formatBytes(value: number) {
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

function formatExpiry(value: string | null) {
  if (!value) return 'No expiry configured'
  try {
    return formatDistanceToNow(parseISO(value), { addSuffix: true })
  } catch (_error) {
    return value
  }
}

function renderLimit(limit: number) {
  if (!limit || limit <= 0) return 'Unlimited'
  return limit.toLocaleString()
}

function UsageSnapshots({ snapshots }: { snapshots: AgentProfile['usage_snapshots'] }) {
  if (snapshots.length === 0) {
    return <p className='text-sm text-muted-foreground'>No recent user activity recorded.</p>
  }

  return (
    <div className='overflow-hidden rounded-md border'>
      <table className='w-full text-sm'>
        <thead className='bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground'>
          <tr>
            <th className='px-3 py-2 text-left'>User</th>
            <th className='px-3 py-2 text-right'>Used</th>
            <th className='px-3 py-2 text-right'>Plan</th>
            <th className='px-3 py-2 text-right'>Expires</th>
          </tr>
        </thead>
        <tbody>
          {snapshots.map((snapshot) => {
            const expireLabel = snapshot.expire_at ? formatExpiry(snapshot.expire_at) : '—'
            return (
              <tr key={snapshot.username} className='odd:bg-muted/20'>
                <td className='px-3 py-2 font-medium'>{snapshot.username}</td>
                <td className='px-3 py-2 text-right font-mono text-xs'>
                  {formatBytes(snapshot.used_bytes)}
                </td>
                <td className='px-3 py-2 text-right font-mono text-xs'>
                  {snapshot.plan_limit_bytes > 0 ? formatBytes(snapshot.plan_limit_bytes) : 'Unlimited'}
                </td>
                <td className='px-3 py-2 text-right text-xs text-muted-foreground'>{expireLabel}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function AgentOverview() {
  const { data, isPending, isError, error } = useAgentProfileQuery()

  if (isPending) {
    return (
      <div className='grid gap-6 lg:grid-cols-[2fr,1fr]'>
        <Card>
          <CardHeader>
            <CardTitle className='text-lg'>Account overview</CardTitle>
          </CardHeader>
          <CardContent className='space-y-4'>
            <Skeleton className='h-16 w-full rounded-lg' />
            <Skeleton className='h-16 w-full rounded-lg' />
            <Skeleton className='h-24 w-full rounded-lg' />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className='text-lg'>Usage snapshots</CardTitle>
          </CardHeader>
          <CardContent>
            <Skeleton className='h-40 w-full rounded-lg' />
          </CardContent>
        </Card>
      </div>
    )
  }

  if (isError || !data) {
    const message =
      error instanceof Error ? error.message : 'Unable to load your agent profile.'
    return (
      <Alert variant='destructive'>
        <AlertTitle>Account data unavailable</AlertTitle>
        <AlertDescription>{message}</AlertDescription>
      </Alert>
    )
  }

  const quotaPercent = data.plan_limit_bytes
    ? Math.min(100, (data.total_used_bytes / data.plan_limit_bytes) * 100)
    : 0

  return (
    <div className='grid gap-6 lg:grid-cols-[2fr,1fr]'>
      <Card>
        <CardHeader>
          <div className='flex items-center justify-between'>
            <div>
              <CardTitle className='text-lg'>Account overview</CardTitle>
              <p className='text-sm text-muted-foreground'>Live metrics for your agent tenancy.</p>
            </div>
            <AgentStatusBadge active={data.active} />
          </div>
        </CardHeader>
        <CardContent className='grid gap-4 lg:grid-cols-2'>
          <div className='space-y-1 rounded-lg border bg-muted/40 p-4'>
            <p className='text-xs uppercase text-muted-foreground'>Plan quota</p>
            <p className='text-lg font-semibold'>{formatBytes(data.plan_limit_bytes)}</p>
            <p className='text-xs text-muted-foreground'>
              {data.plan_limit_bytes
                ? `${quotaPercent.toFixed(1)}% consumed (${formatBytes(data.total_used_bytes)} used)`
                : `${formatBytes(data.total_used_bytes)} consumed`}
            </p>
          </div>

          <div className='space-y-1 rounded-lg border bg-muted/40 p-4'>
            <p className='text-xs uppercase text-muted-foreground'>Users</p>
            <p className='text-lg font-semibold'>{data.total_users.toLocaleString()}</p>
            <p className='text-xs text-muted-foreground'>
              Limit: {renderLimit(data.user_limit)}
            </p>
          </div>

          <div className='space-y-1 rounded-lg border bg-muted/40 p-4'>
            <p className='text-xs uppercase text-muted-foreground'>Per-user cap</p>
            <p className='text-lg font-semibold'>
              {data.max_user_bytes > 0 ? formatBytes(data.max_user_bytes) : 'Unlimited'}
            </p>
            <p className='text-xs text-muted-foreground'>
              Enforced on each subscriber managed by this agent.
            </p>
          </div>

          <div className='space-y-1 rounded-lg border bg-muted/40 p-4'>
            <p className='text-xs uppercase text-muted-foreground'>Expiry</p>
            <p className='text-lg font-semibold'>{formatExpiry(data.expire_at)}</p>
            <p className='text-xs text-muted-foreground'>
              Created {formatDistanceToNow(parseISO(data.created_at), { addSuffix: true })}
            </p>
          </div>
        </CardContent>
      </Card>

      <Card className='lg:row-span-2'>
        <CardHeader>
          <CardTitle className='flex items-center gap-2'>
            Usage snapshots
            <Badge variant='outline'>Top {data.usage_snapshots.length || 0}</Badge>
          </CardTitle>
          <p className='text-sm text-muted-foreground'>Recent consumption for your busiest users.</p>
        </CardHeader>
        <CardContent>
          <UsageSnapshots snapshots={data.usage_snapshots} />
        </CardContent>
      </Card>
    </div>
  )
}
