import { ServiceFormDialog } from './service-form-dialog'
import { ServiceDeleteDialog } from './service-delete-dialog'
import { ServicePanelsDialog } from './service-panels-dialog'
import { useServices } from './services-provider'

export function ServicesDialogs() {
  const { open, setOpen, currentService, setCurrentService } = useServices()

  const closeDialogs = () => {
    setOpen(null)
    setCurrentService(null)
  }

  const isFormOpen = open === 'create' || open === 'edit'
  const formMode = open === 'edit' ? 'edit' : 'create'
  const deleteOpen = open === 'delete' && !!currentService
  const panelsOpen = open === 'panels' && !!currentService

  return (
    <>
      <ServiceFormDialog
        mode={formMode}
        open={isFormOpen}
        onOpenChange={(state) => {
          if (!state) {
            closeDialogs()
          }
        }}
        service={formMode === 'edit' ? currentService ?? undefined : undefined}
      />

      {deleteOpen && currentService ? (
        <ServiceDeleteDialog
          open={deleteOpen}
          onOpenChange={(state) => {
            if (!state) {
              closeDialogs()
            }
          }}
          service={currentService}
        />
      ) : null}

      {panelsOpen && currentService ? (
        <ServicePanelsDialog
          open={panelsOpen}
          onOpenChange={(state) => {
            if (!state) {
              closeDialogs()
            }
          }}
          service={currentService}
        />
      ) : null}
    </>
  )
}
