import {
  Bell,
  Bot,
  GaugeCircle,
  KeyRound,
  LayoutDashboard,
  Monitor,
  Palette,
  Settings2,
  ShieldCheck,
  Users,
  Workflow,
} from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  user: {
    name: 'Valhalla Operator',
    email: 'ops@valhalla.ai',
    avatar: '/avatars/shadcn.jpg',
  },
  teams: [
    {
      name: 'Valhalla Core',
      logo: Bot,
      plan: 'Production',
    },
    {
      name: 'Bifrost QA',
      logo: Workflow,
      plan: 'Staging',
    },
    {
      name: 'Einherjar Lab',
      logo: GaugeCircle,
      plan: 'Sandbox',
    },
  ],
  navGroups: [
    {
      title: 'Console',
      items: [
        {
          title: 'Overview',
          url: '/_authenticated/',
          icon: LayoutDashboard,
        },
        {
          title: 'Users',
          url: '/_authenticated/users/',
          icon: Users,
        },
      ],
    },
    {
      title: 'Administration',
      items: [
        {
          title: 'Agents',
          url: '/_authenticated/admin/agents/',
          icon: KeyRound,
        },
        {
          title: 'Settings',
          icon: Settings2,
          items: [
            {
              title: 'General',
              url: '/_authenticated/settings/',
              icon: Settings2,
            },
            {
              title: 'Access control',
              url: '/_authenticated/settings/account',
              icon: ShieldCheck,
            },
            {
              title: 'Appearance',
              url: '/_authenticated/settings/appearance',
              icon: Palette,
            },
            {
              title: 'Notifications',
              url: '/_authenticated/settings/notifications',
              icon: Bell,
            },
            {
              title: 'Display',
              url: '/_authenticated/settings/display',
              icon: Monitor,
            },
          ],
        },
      ],
    },
  ],
}
