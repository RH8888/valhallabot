import { isAxiosError } from 'axios'
import { getRouteApi } from '@tanstack/react-router'
import { format } from 'date-fns'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'
import { LoadingOverlay } from '@/components/ui/loading-indicator'
import { usePanelQuery } from '@/lib/api/panels'
import { PanelsDialogs } from './components/panels-dialogs'
import { PanelsProvider, usePanels } from './components/panels-provider'
import { PANEL_TYPES } from './constants'

const route = getRouteApi('/_authenticated/panels/$panelId')

const PANEL_TYPE_LABELS = new Map(PANEL_TYPES.map((type) => [type.value, type.label]))

function PanelDetailContent() {
  const { panelId } = route.useParams()
  const numericId = Number(panelId)
  const isValidId = Number.isFinite(numericId)

  const { data: panel, isPending, isError, error } = usePanelQuery(numericId, isValidId)
  const { setCurrentPanel, setOpen } = usePanels()

  let errorMessage: string | null = null
  if (!isValidId) {
    errorMessage = 'The requested panel identifier is invalid.'
  } else if (isError) {
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
      errorMessage = 'Unable to load panel details.'
    }
  }

  const handleOpenDialog = (dialog: 'edit' | 'disable' | 'delete') => {
    if (!panel) return
    setCurrentPanel(panel)
    setOpen(dialog)
  }

  return (
    <>
      <Header fixed>
        <div className='ms-auto flex items-center space-x-4'>
          <ThemeSwitch />
          <ConfigDrawer />
          <ProfileDropdown />
        </div>
      </Header>

      <Main className='flex flex-1 flex-col gap-4 sm:gap-6'>
        {errorMessage && (
          <Alert variant='destructive'>
            <AlertTitle>Unable to load panel</AlertTitle>
            <AlertDescription className='whitespace-pre-line'>
              {errorMessage}
            </AlertDescription>
          </Alert>
        )}

        {isPending ? (
          <div className='flex flex-1 items-center justify-center'>
            <LoadingOverlay label='Loading panel…' />
          </div>
        ) : panel ? (
          <div className='flex flex-col gap-6'>
            <div className='flex flex-wrap items-start justify-between gap-4'>
              <div>
                <div className='flex flex-wrap items-center gap-3'>
                  <h2 className='text-3xl font-bold tracking-tight'>{panel.name}</h2>
                  <Badge variant='outline'>
                    {PANEL_TYPE_LABELS.get(panel.panel_type) ?? panel.panel_type}
                  </Badge>
                </div>
                <p className='text-muted-foreground'>
                  Created{' '}
                  <time dateTime={panel.created_at}>
                    {format(new Date(panel.created_at), 'PPpp')}
                  </time>
                </p>
              </div>
              <div className='flex flex-wrap items-center gap-2'>
                <Button variant='outline' onClick={() => handleOpenDialog('edit')}>
                  Edit panel
                </Button>
                <Button
                  variant='outline'
                  onClick={() => handleOpenDialog('disable')}
                  className='border-amber-500 text-amber-600 hover:bg-amber-500/10 dark:border-amber-400 dark:text-amber-300 dark:hover:bg-amber-400/10'
                >
                  Disable
                </Button>
                <Button variant='destructive' onClick={() => handleOpenDialog('delete')}>
                  Delete
                </Button>
              </div>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Connection details</CardTitle>
              </CardHeader>
              <CardContent>
                <dl className='grid gap-4 sm:grid-cols-2'>
                  <div>
                    <dt className='text-sm font-medium text-muted-foreground'>Panel URL</dt>
                    <dd className='mt-1 break-all text-sm'>
                      <a
                        href={panel.panel_url}
                        target='_blank'
                        rel='noreferrer'
                        className='text-primary underline-offset-4 hover:underline'
                      >
                        {panel.panel_url}
                      </a>
                    </dd>
                  </div>
                  <div>
                    <dt className='text-sm font-medium text-muted-foreground'>Subscription link</dt>
                    <dd className='mt-1 break-all text-sm text-muted-foreground'>
                      {panel.sub_url ? (
                        <a
                          href={panel.sub_url}
                          target='_blank'
                          rel='noreferrer'
                          className='text-primary underline-offset-4 hover:underline'
                        >
                          {panel.sub_url}
                        </a>
                      ) : (
                        'Not configured'
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className='text-sm font-medium text-muted-foreground'>Admin username</dt>
                    <dd className='mt-1 text-sm font-mono'>{panel.admin_username}</dd>
                  </div>
                  <div>
                    <dt className='text-sm font-medium text-muted-foreground'>Template user</dt>
                    <dd className='mt-1 text-sm text-muted-foreground'>
                      {panel.template_username ?? 'Not configured'}
                    </dd>
                  </div>
                  <div>
                    <dt className='text-sm font-medium text-muted-foreground'>Access token</dt>
                    <dd className='mt-1 text-sm font-mono text-muted-foreground'>
                      Hidden for security. Rotate the token from the edit dialog if required.
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          </div>
        ) : null}
      </Main>

      <PanelsDialogs />
    </>
  )
}

export function PanelDetail() {
  return (
    <PanelsProvider>
      <PanelDetailContent />
    </PanelsProvider>
  )
}
