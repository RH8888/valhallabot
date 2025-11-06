import { isAxiosError } from 'axios'
import { getRouteApi } from '@tanstack/react-router'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { useServicesQuery } from '@/lib/api/services'
import { ServicesDialogs } from './components/services-dialogs'
import { ServicesPrimaryButtons } from './components/services-primary-buttons'
import { ServicesProvider } from './components/services-provider'
import { ServicesTable } from './components/services-table'

const route = getRouteApi('/_authenticated/admin/services/')

export function ServicesAdmin() {
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const { data, isPending, isError, error } = useServicesQuery()

  const services = data ?? []

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
      errorMessage = 'Unable to load services.'
    }
  }

  return (
    <ServicesProvider>
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
            <h2 className='text-2xl font-bold tracking-tight'>Service catalog</h2>
            <p className='text-muted-foreground'>
              Group panels and users into cohesive services to streamline automation and reporting.
            </p>
          </div>
          <ServicesPrimaryButtons />
        </div>

        {errorMessage && (
          <Alert variant='destructive'>
            <AlertTitle>Unable to fetch services</AlertTitle>
            <AlertDescription className='whitespace-pre-line'>
              {errorMessage}
            </AlertDescription>
          </Alert>
        )}

        <ServicesTable
          data={services}
          search={search}
          navigate={navigate}
          isLoading={isPending}
        />
      </Main>

      <ServicesDialogs />
    </ServicesProvider>
  )
}
