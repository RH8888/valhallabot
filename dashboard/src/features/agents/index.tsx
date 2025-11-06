import { isAxiosError } from 'axios'
import { getRouteApi } from '@tanstack/react-router'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { useAgentsQuery } from '@/lib/api/agents'
import { AgentsTable } from './components/agents-table'

const route = getRouteApi('/_authenticated/admin/agents/')

export function AgentsAdmin() {
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const { data, isPending, isError, error } = useAgentsQuery()

  const agents = data ?? []

  let errorMessage: string | null = null
  if (isError) {
    if (isAxiosError(error)) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') {
        errorMessage = detail
      } else if (Array.isArray(detail)) {
        errorMessage = detail.join('\n')
      } else {
        errorMessage = error.message
      }
    } else if (error instanceof Error) {
      errorMessage = error.message
    } else {
      errorMessage = 'Unable to load agents.'
    }
  }

  return (
    <>
      <Header fixed>
        <Search />
        <div className='ms-auto flex items-center space-x-4'>
          <ThemeSwitch />
          <ConfigDrawer />
          <ProfileDropdown />
        </div>
      </Header>

      <Main className='flex flex-1 flex-col gap-4 sm:gap-6'>
        <div className='flex flex-wrap items-end justify-between gap-2'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>Agent control</h2>
            <p className='text-muted-foreground'>
              Review quotas, enforce limits, and rotate credentials for every agent in one place.
            </p>
          </div>
        </div>

        {errorMessage ? (
          <Alert variant='destructive'>
            <AlertTitle>Unable to fetch agents</AlertTitle>
            <AlertDescription className='whitespace-pre-line'>{errorMessage}</AlertDescription>
          </Alert>
        ) : null}

        <AgentsTable
          data={agents}
          search={search}
          navigate={navigate}
          isLoading={isPending}
        />
      </Main>
    </>
  )
}
