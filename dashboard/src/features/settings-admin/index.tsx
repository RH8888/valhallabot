import { useMemo, useState } from 'react'
import { isAxiosError } from 'axios'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'
import { useSettingsQuery } from '@/lib/api/settings'
import type { Setting } from '@/lib/api/types'
import { SettingDeleteDialog } from './components/setting-delete-dialog'
import { SettingEditDialog } from './components/setting-edit-dialog'
import { SettingsCategoryCard } from './components/settings-category-card'
import { deriveSettingMetadata, type SettingMetadata } from './settings-metadata'

type SettingEntry = {
  setting: Setting
  metadata: SettingMetadata
}

type CategoryGroup = {
  id: string
  title: string
  description: string
  items: SettingEntry[]
}

function groupSettings(settings: Setting[]): CategoryGroup[] {
  const groups = new Map<string, CategoryGroup>()

  for (const setting of settings) {
    const metadata = deriveSettingMetadata(setting)
    const existing = groups.get(metadata.category.id)

    if (existing) {
      existing.items.push({ setting, metadata })
    } else {
      groups.set(metadata.category.id, {
        id: metadata.category.id,
        title: metadata.category.title,
        description: metadata.category.description,
        items: [{ setting, metadata }],
      })
    }
  }

  return Array.from(groups.values()).map((group) => ({
    ...group,
    items: group.items.sort((a, b) => a.metadata.label.localeCompare(b.metadata.label)),
  }))
}

function sortGroups(groups: CategoryGroup[]) {
  const order = ['emergency', 'security', 'limits', 'notifications', 'automation']
  return [...groups].sort((a, b) => {
    const indexA = order.indexOf(a.id)
    const indexB = order.indexOf(b.id)

    if (indexA !== -1 || indexB !== -1) {
      if (indexA === -1) return 1
      if (indexB === -1) return -1
      return indexA - indexB
    }

    return a.title.localeCompare(b.title)
  })
}

type ActiveDialog = {
  setting: Setting
  metadata: SettingMetadata
} | null

function SettingsSkeleton() {
  return (
    <div className='grid gap-6 lg:grid-cols-2'>
      {[0, 1, 2, 3].map((item) => (
        <div key={item} className='space-y-4 rounded-xl border p-6'>
          <div className='space-y-2'>
            <Skeleton className='h-5 w-1/3' />
            <Skeleton className='h-4 w-3/4' />
          </div>
          <div className='space-y-4'>
            {[0, 1].map((row) => (
              <div key={row} className='space-y-3'>
                <div className='space-y-2'>
                  <Skeleton className='h-4 w-2/3' />
                  <Skeleton className='h-3 w-full' />
                </div>
                <Skeleton className='h-16 w-full' />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function SettingsAdmin() {
  const { data, isPending, isError, error } = useSettingsQuery()
  const [editing, setEditing] = useState<ActiveDialog>(null)
  const [deleting, setDeleting] = useState<ActiveDialog>(null)

  const grouped = useMemo(() => {
    const entries = data ?? []
    const groups = groupSettings(entries)
    return sortGroups(groups)
  }, [data])

  let errorMessage: string | null = null
  if (isError) {
    if (isAxiosError(error)) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') {
        errorMessage = detail
      } else if (Array.isArray(detail) && detail.length > 0) {
        errorMessage = detail.join('\n')
      } else {
        errorMessage = error.message
      }
    } else if (error instanceof Error) {
      errorMessage = error.message
    } else {
      errorMessage = 'Unable to load settings.'
    }
  }

  const handleEdit = (setting: Setting, metadata: SettingMetadata) => {
    setEditing({ setting, metadata })
  }

  const handleDelete = (setting: Setting, metadata: SettingMetadata) => {
    setDeleting({ setting, metadata })
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

      <Main className='flex flex-1 flex-col gap-6'>
        <div className='space-y-1'>
          <h1 className='text-2xl font-bold tracking-tight'>Platform settings</h1>
          <p className='text-muted-foreground'>
            Review and manage cluster-level configuration. Changes apply immediately.
          </p>
        </div>

        {errorMessage && (
          <Alert variant='destructive'>
            <AlertTitle>Unable to fetch settings</AlertTitle>
            <AlertDescription className='whitespace-pre-wrap'>{errorMessage}</AlertDescription>
          </Alert>
        )}

        {isPending ? (
          <SettingsSkeleton />
        ) : grouped.length > 0 ? (
          <div className='grid gap-6 lg:grid-cols-2'>
            {grouped.map((group) => (
              <SettingsCategoryCard
                key={group.id}
                title={group.title}
                description={group.description}
                settings={group.items}
                onEdit={handleEdit}
                onDelete={handleDelete}
              />
            ))}
          </div>
        ) : (
          <Alert>
            <AlertTitle>No settings found</AlertTitle>
            <AlertDescription>
              The API did not return any configurable settings. Once settings exist they will appear here for review.
            </AlertDescription>
          </Alert>
        )}
      </Main>

      <SettingEditDialog
        open={Boolean(editing)}
        onOpenChange={(open) => {
          if (!open) setEditing(null)
        }}
        setting={editing?.setting ?? null}
        metadata={editing?.metadata ?? null}
      />

      <SettingDeleteDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
        setting={deleting?.setting ?? null}
        metadata={deleting?.metadata ?? null}
      />
    </>
  )
}
