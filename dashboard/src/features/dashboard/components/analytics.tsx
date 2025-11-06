import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { type QuotaBreakdownItem } from '../hooks/use-dashboard-metrics'

type AnalyticsProps = {
  channelBreakdown: QuotaBreakdownItem[]
  topIntents: QuotaBreakdownItem[]
}

export function Analytics({ channelBreakdown, topIntents }: AnalyticsProps) {
  return (
    <div className='grid gap-4 md:grid-cols-2'>
      <Card>
        <CardHeader>
          <CardTitle>Channel usage</CardTitle>
        </CardHeader>
        <CardContent>
          <SimpleBarList
            items={channelBreakdown}
            valueFormatter={(n) => `${n.toLocaleString()}`}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Top intents</CardTitle>
        </CardHeader>
        <CardContent>
          <SimpleBarList
            items={topIntents}
            valueFormatter={(n) => `${n}%`}
          />
        </CardContent>
      </Card>
    </div>
  )
}

function SimpleBarList({
  items,
  valueFormatter,
}: {
  items: QuotaBreakdownItem[]
  valueFormatter: (n: number) => string
}) {
  const max = Math.max(...items.map((i) => i.value), 1)
  return (
    <ul className='space-y-3'>
      {items.map((item) => {
        const width = `${Math.round((item.value / max) * 100)}%`
        return (
          <li key={item.label} className='flex items-center justify-between gap-3'>
            <div className='min-w-0 flex-1'>
              <div className='text-muted-foreground mb-1 truncate text-xs'>
                {item.label}
              </div>
              <div className='bg-muted h-2.5 w-full rounded-full'>
                <div
                  className='bg-primary h-2.5 rounded-full'
                  style={{ width }}
                />
              </div>
            </div>
            <div className='ps-2 text-xs font-medium tabular-nums'>
              {valueFormatter(item.value)}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
