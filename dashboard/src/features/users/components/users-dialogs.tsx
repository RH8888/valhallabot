import { UsersActionDialog, type ServiceOption } from './users-action-dialog'
import { UsersRenewDialog } from './users-renew-dialog'
import { useUsers } from './users-provider'

type UsersDialogsProps = {
  services: ServiceOption[]
  isLoadingServices?: boolean
}

export function UsersDialogs({ services, isLoadingServices }: UsersDialogsProps) {
  const { open, setOpen, currentRow, setCurrentRow } = useUsers()

  return (
    <>
      <UsersActionDialog
        key='user-create'
        mode='create'
        open={open === 'create'}
        onOpenChange={(state) => {
          if (!state) {
            setOpen('create')
          }
        }}
        services={services}
        isLoadingServices={isLoadingServices}
      />

      {currentRow && (
        <>
          <UsersActionDialog
            key={`user-edit-${currentRow.username}`}
            mode='edit'
            user={currentRow}
            open={open === 'edit'}
            onOpenChange={(state) => {
              if (!state) {
                setOpen('edit')
                setTimeout(() => {
                  setCurrentRow(null)
                }, 150)
              }
            }}
            services={services}
            isLoadingServices={isLoadingServices}
          />

          <UsersRenewDialog
            key={`user-renew-${currentRow.username}`}
            user={currentRow}
            open={open === 'renew'}
            onOpenChange={(state) => {
              if (!state) {
                setOpen('renew')
                setTimeout(() => {
                  setCurrentRow(null)
                }, 150)
              }
            }}
          />
        </>
      )}
    </>
  )
}
