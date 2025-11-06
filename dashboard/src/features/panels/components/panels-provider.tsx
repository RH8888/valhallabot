import { createContext, useContext, useState } from 'react'
import useDialogState from '@/hooks/use-dialog-state'
import type { Panel } from '@/lib/api/types'

type PanelDialogType = 'create' | 'edit' | 'delete' | 'disable'

type PanelsContextValue = {
  open: PanelDialogType | null
  setOpen: (value: PanelDialogType | null) => void
  currentPanel: Panel | null
  setCurrentPanel: (panel: Panel | null) => void
}

const PanelsContext = createContext<PanelsContextValue | null>(null)

type PanelsProviderProps = {
  children: React.ReactNode
}

export function PanelsProvider({ children }: PanelsProviderProps) {
  const [open, setOpen] = useDialogState<PanelDialogType>(null)
  const [currentPanel, setCurrentPanel] = useState<Panel | null>(null)

  return (
    <PanelsContext.Provider value={{ open, setOpen, currentPanel, setCurrentPanel }}>
      {children}
    </PanelsContext.Provider>
  )
}

export function usePanels() {
  const context = useContext(PanelsContext)
  if (!context) {
    throw new Error('usePanels must be used within a PanelsProvider')
  }
  return context
}
