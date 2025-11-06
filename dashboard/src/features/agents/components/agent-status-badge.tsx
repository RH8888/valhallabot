import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'

type AgentStatusBadgeProps = {
  active: boolean
}

export function AgentStatusBadge({ active }: AgentStatusBadgeProps) {
  if (active) {
    return (
      <Badge
        variant='secondary'
        className={cn(
          'border-emerald-500/40 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
        )}
      >
        Active
      </Badge>
    )
  }

  return (
    <Badge
      variant='outline'
      className='border-destructive/50 text-destructive dark:text-destructive-foreground'
    >
      Inactive
    </Badge>
  )
}
