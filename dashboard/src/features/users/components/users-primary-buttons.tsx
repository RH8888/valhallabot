import { UserPlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useUsers } from './users-provider'

export function UsersPrimaryButtons() {
  const { setOpen, setCurrentRow } = useUsers()

  return (
    <Button
      className='space-x-1'
      onClick={() => {
        setCurrentRow(null)
        setOpen('create')
      }}
    >
      <span>Create User</span> <UserPlus size={18} />
    </Button>
  )
}
