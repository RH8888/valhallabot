import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useServices } from './services-provider'

export function ServicesPrimaryButtons() {
  const { setOpen, setCurrentService } = useServices()

  return (
    <Button
      onClick={() => {
        setCurrentService(null)
        setOpen('create')
      }}
      className='inline-flex items-center gap-2'
    >
      <Plus className='h-4 w-4' />
      New service
    </Button>
  )
}
