import { useEffect, useMemo } from 'react'
import { getRouteApi } from '@tanstack/react-router'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search as GlobalSearch } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { useServicesQuery } from '@/lib/api/services'
import { useUsersQuery } from '@/lib/api/users'
import { UsersDialogs } from './components/users-dialogs'
import { UsersFilters } from './components/users-filters'
import { UsersPrimaryButtons } from './components/users-primary-buttons'
import { UsersProvider } from './components/users-provider'
import { UsersTable } from './components/users-table'

const route = getRouteApi('/_authenticated/users/')

export function Users() {
  const search = route.useSearch()
  const navigate = route.useNavigate()

  const page = search.page ?? 1
  const pageSize = search.pageSize ?? 10
  const usernameFilter = search.username ?? ''
  const serviceIdFilter = search.serviceId
  const statusFilter = search.status

  const disabledFilter = statusFilter === 'disabled' ? true : statusFilter === 'active' ? false : undefined

  const request = useMemo(
    () => ({
      offset: Math.max(0, (page - 1) * pageSize),
      limit: pageSize,
      search: usernameFilter.trim() ? usernameFilter.trim() : undefined,
      service_id: serviceIdFilter ?? undefined,
      disabled: disabledFilter,
    }),
    [page, pageSize, usernameFilter, serviceIdFilter, disabledFilter]
  )

  const usersQuery = useUsersQuery(request)
  const servicesQuery = useServicesQuery()

  const serviceOptions = useMemo(
    () =>
      servicesQuery.data?.map((service) => ({
        label: service.name,
        value: service.id,
      })) ?? [],
    [servicesQuery.data]
  )

  const serviceMap = useMemo(() => {
    const map = new Map<number, string>()
    for (const option of serviceOptions) {
      map.set(option.value, option.label)
    }
    return map
  }, [serviceOptions])

  const userRows = useMemo(
    () =>
      (usersQuery.data?.users ?? []).map((user) => ({
        ...user,
        serviceName:
          user.service_id !== null && user.service_id !== undefined
            ? serviceMap.get(user.service_id) ?? null
            : null,
      })),
    [usersQuery.data?.users, serviceMap]
  )

  const handlePageChange = (nextPage: number) => {
    navigate({
      search: (prev) => ({
        ...prev,
        page: nextPage <= 1 ? undefined : nextPage,
      }),
    })
  }

  const handlePageSizeChange = (nextPageSize: number) => {
    navigate({
      search: (prev) => ({
        ...prev,
        page: undefined,
        pageSize: nextPageSize === 10 ? undefined : nextPageSize,
      }),
    })
  }

  const handleUsernameChange = (value: string) => {
    navigate({
      search: (prev) => ({
        ...prev,
        page: undefined,
        username: value ? value : undefined,
      }),
    })
  }

  const handleServiceChange = (serviceId: number | undefined) => {
    navigate({
      search: (prev) => ({
        ...prev,
        page: undefined,
        serviceId: serviceId === undefined ? undefined : serviceId,
      }),
    })
  }

  const handleStatusChange = (status: 'active' | 'disabled' | undefined) => {
    navigate({
      search: (prev) => ({
        ...prev,
        page: undefined,
        status,
      }),
    })
  }

  const totalPages = useMemo(() => {
    const total = usersQuery.data?.total ?? 0
    return Math.max(1, Math.ceil(total / pageSize))
  }, [usersQuery.data?.total, pageSize])

  useEffect(() => {
    if (!usersQuery.isFetching && page > totalPages) {
      navigate({
        search: (prev) => ({
          ...prev,
          page: totalPages <= 1 ? undefined : totalPages,
        }),
      })
    }
  }, [page, totalPages, usersQuery.isFetching, navigate])

  return (
    <UsersProvider>
      <Header fixed>
        <GlobalSearch />
        <div className='ms-auto flex items-center space-x-4'>
          <ThemeSwitch />
          <ConfigDrawer />
          <ProfileDropdown />
        </div>
      </Header>

      <Main className='flex flex-1 flex-col gap-4 sm:gap-6'>
        <div className='flex flex-wrap items-end justify-between gap-2'>
          <div>
            <h2 className='text-2xl font-bold tracking-tight'>User List</h2>
            <p className='text-muted-foreground'>
              Manage your users, usage quotas, and service assignments.
            </p>
          </div>
          <UsersPrimaryButtons />
        </div>

        <UsersFilters
          username={usernameFilter}
          status={statusFilter}
          serviceId={serviceIdFilter}
          onUsernameChange={handleUsernameChange}
          onStatusChange={handleStatusChange}
          onServiceChange={handleServiceChange}
          services={serviceOptions}
          isLoadingServices={servicesQuery.isLoading}
        />

        {usersQuery.isError && (
          <Alert variant='destructive'>
            <AlertTitle>Failed to load users</AlertTitle>
            <AlertDescription>
              {usersQuery.error instanceof Error
                ? usersQuery.error.message
                : 'An unexpected error occurred while fetching users.'}
            </AlertDescription>
          </Alert>
        )}

        <UsersTable
          data={userRows}
          total={usersQuery.data?.total ?? 0}
          page={page}
          pageSize={pageSize}
          onPageChange={handlePageChange}
          onPageSizeChange={handlePageSizeChange}
          isLoading={usersQuery.isLoading}
          isFetching={usersQuery.isFetching}
        />
      </Main>

      <UsersDialogs
        services={serviceOptions}
        isLoadingServices={servicesQuery.isLoading}
      />
    </UsersProvider>
  )
}
