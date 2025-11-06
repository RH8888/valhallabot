import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { usePanels } from './panels-provider'

export function PanelsPrimaryButtons() {
  const { setOpen, setCurrentPanel } = usePanels()

  return (
    <div className='flex gap-2'>
      <Button
        className='space-x-1'
        onClick={() => {
          setCurrentPanel(null)
          setOpen('create')
        }}
      >
        <span>New panel</span>
        <Plus size={18} />
      </Button>
    </div>
  )
}
