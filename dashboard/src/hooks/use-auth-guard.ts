import { useEffect } from 'react'
import { useLocation, useNavigate } from '@tanstack/react-router'
import { useAuthStore } from '@/stores/auth-store'
import { applyAuthToken } from '@/lib/http-client'

export function useAuthGuard() {
  const navigate = useNavigate()
  const location = useLocation()
  const token = useAuthStore((state) => state.token)

  useEffect(() => {
    if (!token) {
      const redirectUrl = location.href ?? `${location.pathname}${location.search ?? ''}`
      navigate({
        to: '/sign-in',
        search: { redirect: redirectUrl },
        replace: true,
      })
      return
    }

    applyAuthToken(token)
  }, [token, navigate, location.href, location.pathname, location.search])
}
