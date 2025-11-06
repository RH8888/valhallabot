import { PanelDeleteDialog } from './panel-delete-dialog'
import { PanelDisableDialog } from './panel-disable-dialog'
import { PanelFormDialog } from './panel-form-dialog'
import { usePanels } from './panels-provider'

export function PanelsDialogs() {
  const { open, setOpen, currentPanel, setCurrentPanel } = usePanels()

  return (
    <>
      <PanelFormDialog
        key='panel-create'
        mode='create'
        open={open === 'create'}
        onOpenChange={() => setOpen('create')}
      />

      {currentPanel && (
        <>
          <PanelFormDialog
            key={`panel-edit-${currentPanel.id}`}
            mode='edit'
            panel={currentPanel}
            open={open === 'edit'}
            onOpenChange={(state) => {
              if (!state) {
                setOpen('edit')
                setTimeout(() => setCurrentPanel(null), 150)
              }
            }}
          />

          <PanelDisableDialog
            key={`panel-disable-${currentPanel.id}`}
            panel={currentPanel}
            open={open === 'disable'}
            onOpenChange={(state) => {
              if (!state) {
                setOpen('disable')
                setTimeout(() => setCurrentPanel(null), 150)
              }
            }}
          />

          <PanelDeleteDialog
            key={`panel-delete-${currentPanel.id}`}
            panel={currentPanel}
            open={open === 'delete'}
            onOpenChange={(state) => {
              if (!state) {
                setOpen('delete')
                setTimeout(() => setCurrentPanel(null), 150)
              }
            }}
          />
        </>
      )}
    </>
  )
}
