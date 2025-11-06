import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { type ConversationTrendPoint } from '../hooks/use-dashboard-metrics'

type OverviewProps = {
  data: ConversationTrendPoint[]
}

export function Overview({ data }: OverviewProps) {
  return (
    <ResponsiveContainer width='100%' height={320}>
      <BarChart data={data}>
        <XAxis
          dataKey='label'
          stroke='#888888'
          fontSize={12}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          stroke='#888888'
          fontSize={12}
          tickLine={false}
          axisLine={false}
          tickFormatter={(value) => `${value}`}
        />
        <Bar
          dataKey='total'
          fill='currentColor'
          radius={[6, 6, 0, 0]}
          className='fill-primary'
        />
      </BarChart>
    </ResponsiveContainer>
  )
}
