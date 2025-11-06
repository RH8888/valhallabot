import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { type RecentActivityItem } from '../hooks/use-dashboard-metrics'

type RecentActivityProps = {
  items: RecentActivityItem[]
}

export function RecentActivity({ items }: RecentActivityProps) {
  return (
    <ul className='space-y-6'>
      {items.map((item) => (
        <li key={item.id} className='flex items-center gap-4'>
          <Avatar className='h-9 w-9 border'>
            <AvatarFallback className='text-xs uppercase'>
              {item.actor
                .split(' ')
                .map((word) => word[0])
                .slice(0, 2)
                .join('')}
            </AvatarFallback>
          </Avatar>
          <div className='flex flex-1 flex-wrap items-baseline justify-between gap-x-3 gap-y-1'>
            <div className='space-y-1'>
              <p className='text-sm font-medium'>{item.actor}</p>
              <p className='text-muted-foreground text-xs'>{item.detail}</p>
            </div>
            <p className='text-muted-foreground text-xs font-medium tabular-nums'>
              {item.timestamp}
            </p>
          </div>
        </li>
      ))}
    </ul>
  )
}
