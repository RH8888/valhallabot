import { createFileRoute, redirect } from '@tanstack/react-router'
import { AuthenticatedLayout } from '@/components/layout/authenticated-layout'
import { useAuthStore } from '@/stores/auth-store'

export const Route = createFileRoute('/_authenticated')({
  beforeLoad: ({ location }) => {
    const { isAuthenticated } = useAuthStore.getState()
    if (!isAuthenticated()) {
      const redirectUrl = location.href ?? `${location.pathname}${location.search ?? ''}`
      throw redirect({
        to: '/sign-in',
        search: { redirect: redirectUrl },
      })
    }
  },
  component: AuthenticatedLayout,
})
