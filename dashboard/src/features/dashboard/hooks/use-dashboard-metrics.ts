import { useMemo } from 'react'

export type MetricSummary = {
  id: 'totalUsers' | 'activeUsers' | 'dailyConversations' | 'quotaUsage'
  label: string
  value: string
  change: string
  changeDescription: string
}

export type ConversationTrendPoint = {
  label: string
  total: number
}

export type QuotaBreakdownItem = {
  label: string
  value: number
}

export type RecentActivityItem = {
  id: string
  actor: string
  detail: string
  timestamp: string
}

export type DashboardMetrics = {
  metrics: MetricSummary[]
  conversationTrend: ConversationTrendPoint[]
  quota: {
    used: number
    limit: number
  }
  channelBreakdown: QuotaBreakdownItem[]
  topIntents: QuotaBreakdownItem[]
  recentActivity: RecentActivityItem[]
}

export function useDashboardMetrics(): DashboardMetrics {
  // TODO: Replace memoised placeholder data with API driven hooks
  // once telemetry endpoints are available.
  return useMemo(
    () => ({
      metrics: [
        {
          id: 'totalUsers',
          label: 'Total Users',
          value: '4,812',
          change: '+3.4%',
          changeDescription: 'vs last 7 days',
        },
        {
          id: 'activeUsers',
          label: 'Active Sessions',
          value: '127',
          change: '+5.1%',
          changeDescription: 'live in the past hour',
        },
        {
          id: 'dailyConversations',
          label: 'Daily Conversations',
          value: '863',
          change: '+9.0%',
          changeDescription: 'handled by Valhalla',
        },
        {
          id: 'quotaUsage',
          label: 'Quota Used',
          value: '68%',
          change: '-4.7%',
          changeDescription: 'of monthly allocation',
        },
      ],
      conversationTrend: [
        { label: 'Mon', total: 640 },
        { label: 'Tue', total: 712 },
        { label: 'Wed', total: 785 },
        { label: 'Thu', total: 731 },
        { label: 'Fri', total: 804 },
        { label: 'Sat', total: 654 },
        { label: 'Sun', total: 612 },
      ],
      quota: {
        used: 6800,
        limit: 10000,
      },
      channelBreakdown: [
        { label: 'Slack', value: 3240 },
        { label: 'ServiceNow', value: 1680 },
        { label: 'Email', value: 940 },
        { label: 'PagerDuty', value: 520 },
      ],
      topIntents: [
        { label: 'Incident triage', value: 42 },
        { label: 'Deployment updates', value: 28 },
        { label: 'Knowledge lookup', value: 23 },
        { label: 'Access requests', value: 17 },
      ],
      recentActivity: [
        {
          id: 'activity-1',
          actor: 'Maya Chen',
          detail: 'linked the on-call Slack channel',
          timestamp: '2m ago',
        },
        {
          id: 'activity-2',
          actor: 'Luis Herrera',
          detail: 'approved 3 new sandbox users',
          timestamp: '28m ago',
        },
        {
          id: 'activity-3',
          actor: 'Rekha Patel',
          detail: 'uploaded 2 knowledge base articles',
          timestamp: '1h ago',
        },
        {
          id: 'activity-4',
          actor: 'Platform automation',
          detail: 'synced PagerDuty escalation policies',
          timestamp: '3h ago',
        },
        {
          id: 'activity-5',
          actor: 'QA pipeline',
          detail: 'completed regression pack',
          timestamp: '6h ago',
        },
      ],
    }),
    []
  )
}
