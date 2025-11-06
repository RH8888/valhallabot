import { isAxiosError } from 'axios'
import { getRouteApi } from '@tanstack/react-router'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { usePanelsQuery } from '@/lib/api/panels'
import { PanelsDialogs } from './components/panels-dialogs'
import { PanelsPrimaryButtons } from './components/panels-primary-buttons'
import { PanelsProvider } from './components/panels-provider'
import { PanelsTable } from './components/panels-table'

const route = getRouteApi('/_authenticated/panels/')

export function PanelsList() {
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const { data, isPending, isError, error } = usePanelsQuery()

  const panels = data ?? []

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
      errorMessage = 'Unable to load panels.'
    }
  }

  return (
    <PanelsProvider>
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
            <h2 className='text-2xl font-bold tracking-tight'>Panel inventory</h2>
            <p className='text-muted-foreground'>
              Register remote panels, rotate credentials, and monitor availability.
            </p>
          </div>
          <PanelsPrimaryButtons />
        </div>

        {errorMessage && (
          <Alert variant='destructive'>
            <AlertTitle>Unable to fetch panels</AlertTitle>
            <AlertDescription className='whitespace-pre-line'>
              {errorMessage}
            </AlertDescription>
          </Alert>
        )}

        <PanelsTable
          data={panels}
          search={search}
          navigate={navigate}
          isLoading={isPending}
        />
      </Main>

      <PanelsDialogs />
    </PanelsProvider>
  )
}
