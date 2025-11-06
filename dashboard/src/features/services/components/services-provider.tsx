import { createContext, useContext, useState } from 'react'
import useDialogState from '@/hooks/use-dialog-state'
import type { Service } from '@/lib/api/types'

type ServiceDialogType = 'create' | 'edit' | 'delete' | 'panels'

type ServicesContextValue = {
  open: ServiceDialogType | null
  setOpen: (value: ServiceDialogType | null) => void
  currentService: Service | null
  setCurrentService: (service: Service | null) => void
}

const ServicesContext = createContext<ServicesContextValue | null>(null)

type ServicesProviderProps = {
  children: React.ReactNode
}

export function ServicesProvider({ children }: ServicesProviderProps) {
  const [open, setOpen] = useDialogState<ServiceDialogType>(null)
  const [currentService, setCurrentService] = useState<Service | null>(null)

  return (
    <ServicesContext.Provider value={{ open, setOpen, currentService, setCurrentService }}>
      {children}
    </ServicesContext.Provider>
  )
}

export function useServices() {
  const context = useContext(ServicesContext)
  if (!context) {
    throw new Error('useServices must be used within a ServicesProvider')
  }
  return context
}
