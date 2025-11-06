import { useMemo } from 'react'
import { useRouterState } from '@tanstack/react-router'
import {
  Activity,
  GaugeCircle,
  MessageSquareText,
  UsersRound,
} from 'lucide-react'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { TopNav } from '@/components/layout/top-nav'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { Analytics } from './components/analytics'
import { Overview } from './components/overview'
import { RecentActivity } from './components/recent-activity'
import { useDashboardMetrics } from './hooks/use-dashboard-metrics'

const metricIcons = {
  totalUsers: UsersRound,
  activeUsers: Activity,
  dailyConversations: MessageSquareText,
  quotaUsage: GaugeCircle,
} as const

const navItems = [
  { title: 'Overview', href: '/_authenticated/' },
  { title: 'Users', href: '/_authenticated/users/' },
  { title: 'Settings', href: '/_authenticated/settings/' },
] as const

export function Dashboard() {
  const location = useRouterState({ select: (state) => state.location })
  const metrics = useDashboardMetrics()

  const topNavLinks = useMemo(() => {
    const normalize = (path: string) => {
      if (path === '/') return '/'
      return path.replace(/\/+$/, '')
    }
    const activePath = normalize(location.pathname)

    return navItems.map((item) => {
      const target = normalize(item.href)
      const isOverview = target === '/_authenticated'
      const isActive = isOverview
        ? activePath === target
        : activePath.startsWith(target)

      return {
        ...item,
        disabled: false,
        isActive,
      }
    })
  }, [location.pathname])

  const quotaPercent = Math.round(
    (metrics.quota.used / metrics.quota.limit) * 100
  )

  return (
    <>
      <Header>
        <TopNav links={topNavLinks} />
        <div className='ms-auto flex items-center space-x-4'>
          <Search />
          <ThemeSwitch />
          <ConfigDrawer />
          <ProfileDropdown />
        </div>
      </Header>

      <Main className='space-y-6'>
        <div className='flex flex-col gap-2 md:flex-row md:items-center md:justify-between'>
          <div>
            <h1 className='text-2xl font-bold tracking-tight'>Valhalla overview</h1>
            <p className='text-muted-foreground text-sm'>
              Monitor adoption, conversations, and capacity for every bot.
            </p>
          </div>
          <span className='text-muted-foreground text-xs'>
            Mock data • live sync coming soon
          </span>
        </div>

        <div className='grid gap-4 sm:grid-cols-2 lg:grid-cols-4'>
          {metrics.metrics.map((metric) => {
            const Icon = metricIcons[metric.id]
            return (
              <Card key={metric.id}>
                <CardHeader className='flex flex-row items-center justify-between space-y-0 pb-2'>
                  <CardTitle className='text-sm font-medium'>
                    {metric.label}
                  </CardTitle>
                  <Icon className='text-muted-foreground h-4 w-4' />
                </CardHeader>
                <CardContent>
                  <div className='text-2xl font-semibold'>{metric.value}</div>
                  <p className='text-muted-foreground text-xs'>
                    {metric.change} · {metric.changeDescription}
                  </p>
                </CardContent>
              </Card>
            )
          })}
        </div>

        <div className='grid grid-cols-1 gap-4 lg:grid-cols-7'>
          <Card className='lg:col-span-4'>
            <CardHeader>
              <CardTitle>Conversation volume</CardTitle>
              <CardDescription>Requests handled in the last 7 days</CardDescription>
            </CardHeader>
            <CardContent className='ps-0 sm:ps-2'>
              <Overview data={metrics.conversationTrend} />
            </CardContent>
          </Card>
          <Card className='lg:col-span-3'>
            <CardHeader>
              <CardTitle>Quota usage</CardTitle>
              <CardDescription>Monthly interaction allocation</CardDescription>
            </CardHeader>
            <CardContent className='space-y-4'>
              <div>
                <div className='text-2xl font-semibold'>{quotaPercent}%</div>
                <p className='text-muted-foreground text-xs'>
                  {metrics.quota.used.toLocaleString()} of{' '}
                  {metrics.quota.limit.toLocaleString()} interactions consumed
                </p>
              </div>
              <div className='bg-muted h-2 w-full rounded-full'>
                <div
                  className='bg-primary h-2 rounded-full'
                  style={{ width: `${quotaPercent}%` }}
                />
              </div>
              <ul className='space-y-2'>
                {metrics.channelBreakdown.slice(0, 3).map((channel) => (
                  <li
                    key={channel.label}
                    className='flex items-center justify-between text-xs text-muted-foreground'
                  >
                    <span>{channel.label}</span>
                    <span className='font-medium tabular-nums'>
                      {channel.value.toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>

        <div className='grid grid-cols-1 gap-4 lg:grid-cols-7'>
          <div className='lg:col-span-4'>
            <Analytics
              channelBreakdown={metrics.channelBreakdown}
              topIntents={metrics.topIntents}
            />
          </div>
          <Card className='lg:col-span-3'>
            <CardHeader>
              <CardTitle>Recent activity</CardTitle>
            </CardHeader>
            <CardContent>
              <RecentActivity items={metrics.recentActivity} />
            </CardContent>
          </Card>
        </div>
      </Main>
    </>
  )
}
