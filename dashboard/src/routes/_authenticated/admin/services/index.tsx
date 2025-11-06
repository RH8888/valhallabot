import { createFileRoute } from '@tanstack/react-router'
import { ServicesAdmin } from '@/features/services'

export const Route = createFileRoute('/_authenticated/admin/services/')({
  component: ServicesAdmin,
})
