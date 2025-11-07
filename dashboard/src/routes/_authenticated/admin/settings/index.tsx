import { createFileRoute } from '@tanstack/react-router'
import { SettingsAdmin } from '@/features/settings-admin'

export const Route = createFileRoute('/_authenticated/admin/settings/')({
  component: SettingsAdmin,
})
