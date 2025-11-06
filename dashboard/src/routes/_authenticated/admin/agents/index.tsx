import { createFileRoute } from '@tanstack/react-router'
import { AgentsAdmin } from '@/features/agents'

export const Route = createFileRoute('/_authenticated/admin/agents/')({
  component: AgentsAdmin,
})
