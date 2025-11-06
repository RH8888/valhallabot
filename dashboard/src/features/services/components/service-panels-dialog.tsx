import { useEffect, useMemo, useState } from 'react'
import { isAxiosError } from 'axios'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { LoadingOverlay } from '@/components/ui/loading-indicator'
import { usePanelsQuery } from '@/lib/api/panels'
import {
  useServicePanelsQuery,
  useUpdateServicePanelsMutation,
} from '@/lib/api/services'
import type { Panel, Service } from '@/lib/api/types'

type ServicePanelsDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  service: Service
}

export function ServicePanelsDialog({ open, onOpenChange, service }: ServicePanelsDialogProps) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [searchTerm, setSearchTerm] = useState('')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const { data: allPanelsData, isPending: isPanelsPending } = usePanelsQuery()
  const { data: assignmentData, isPending: isAssignmentPending } = useServicePanelsQuery(
    service.id,
    open
  )
  const updateServicePanels = useUpdateServicePanelsMutation(service.id)

  useEffect(() => {
    if (open && assignmentData) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedIds(new Set(assignmentData.panels.map((panel) => panel.id)))
    }
  }, [open, assignmentData])

  useEffect(() => {
    if (!open) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedIds(new Set())
      setSearchTerm('')
      setErrorMessage(null)
    }
  }, [open])

  const sortedPanels = useMemo(() => {
    return [...(allPanelsData ?? [])].sort((a, b) => a.name.localeCompare(b.name))
  }, [allPanelsData])

  const filteredPanels = useMemo(() => {
    const value = searchTerm.trim().toLowerCase()
    if (!value) return sortedPanels
    return sortedPanels.filter((panel) => {
      return (
        panel.name.toLowerCase().includes(value) ||
        panel.panel_url.toLowerCase().includes(value) ||
        (panel.template_username ?? '').toLowerCase().includes(value)
      )
    })
  }, [sortedPanels, searchTerm])

  const assignedPanels = useMemo(
    () => filteredPanels.filter((panel) => selectedIds.has(panel.id)),
    [filteredPanels, selectedIds]
  )
  const availablePanels = useMemo(
    () => filteredPanels.filter((panel) => !selectedIds.has(panel.id)),
    [filteredPanels, selectedIds]
  )

  const handleClose = (state: boolean) => {
    if (!state) {
      setErrorMessage(null)
    }
    onOpenChange(state)
  }

  const togglePanel = (panelId: number, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (checked) {
        next.add(panelId)
      } else {
        next.delete(panelId)
      }
      return next
    })
  }

  const renderPanelList = (panels: Panel[], emptyLabel: string) => {
    if (isPanelsPending || isAssignmentPending) {
      return <LoadingOverlay label='Loading panels…' />
    }
    if (panels.length === 0) {
      return (
        <div className='text-muted-foreground flex h-full items-center justify-center p-4 text-sm'>
          {emptyLabel}
        </div>
      )
    }
    return panels.map((panel) => {
      const panelId = panel.id
      const checked = selectedIds.has(panelId)
      return (
        <label
          key={panelId}
          htmlFor={`panel-${panelId}`}
          className='hover:bg-muted/60 flex items-start gap-3 px-3 py-2'
        >
          <Checkbox
            id={`panel-${panelId}`}
            checked={checked}
            onCheckedChange={(value) =>
              togglePanel(panelId, value === true)
            }
            disabled={updateServicePanels.isPending}
          />
          <div className='space-y-1'>
            <p className='text-sm font-medium leading-none'>{panel.name}</p>
            <p className='text-muted-foreground text-xs'>{panel.panel_url}</p>
          </div>
        </label>
      )
    })
  }

  const handleSubmit = async () => {
    setErrorMessage(null)
    try {
      await updateServicePanels.mutateAsync({
        panel_ids: Array.from(selectedIds.values()),
      })
      handleClose(false)
    } catch (error) {
      let message = 'Failed to update panel assignments.'
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string') {
          message = detail
        } else if (Array.isArray(detail)) {
          message = detail.join('\n')
        }
      }
      setErrorMessage(message)
      toast.error(message)
    }
  }

  const assignedCount = selectedIds.size
  const totalPanels = sortedPanels.length

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className='sm:max-w-3xl'>
        <DialogHeader>
          <DialogTitle>Assign panels to {service.name}</DialogTitle>
          <DialogDescription>
            Choose which panels should be available to this service. The changes apply immediately to
            associated agents and users.
          </DialogDescription>
        </DialogHeader>

        {errorMessage && (
          <Alert variant='destructive'>
            <AlertTitle>Unable to update panels</AlertTitle>
            <AlertDescription className='whitespace-pre-line'>
              {errorMessage}
            </AlertDescription>
          </Alert>
        )}

        <div className='space-y-4'>
          <Input
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder='Filter panels by name or URL...'
          />

          <div className='grid gap-4 md:grid-cols-2'>
            <section>
              <header className='mb-2'>
                <h4 className='text-sm font-semibold'>Assigned panels</h4>
                <p className='text-muted-foreground text-xs'>
                  {assignedCount} of {totalPanels} panels selected.
                </p>
              </header>
              <ScrollArea className='h-64 rounded border'>
                <div className='divide-y'>{renderPanelList(assignedPanels, 'No panels assigned.')}</div>
                <ScrollBar orientation='vertical' />
              </ScrollArea>
            </section>
            <section>
              <header className='mb-2'>
                <h4 className='text-sm font-semibold'>Available panels</h4>
                <p className='text-muted-foreground text-xs'>
                  Panels not currently assigned to this service.
                </p>
              </header>
              <ScrollArea className='h-64 rounded border'>
                <div className='divide-y'>{renderPanelList(availablePanels, 'No additional panels found.')}</div>
                <ScrollBar orientation='vertical' />
              </ScrollArea>
            </section>
          </div>
        </div>

        <DialogFooter>
          <Button variant='outline' onClick={() => handleClose(false)} disabled={updateServicePanels.isPending}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={updateServicePanels.isPending}>
            Save assignments
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
