import { useEffect, useState } from 'react'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { type ServiceOption } from './users-action-dialog'

type UsersFiltersProps = {
  username: string
  status?: 'active' | 'disabled'
  serviceId?: number
  onUsernameChange: (value: string) => void
  onStatusChange: (value: 'active' | 'disabled' | undefined) => void
  onServiceChange: (value: number | undefined) => void
  services: ServiceOption[]
  isLoadingServices?: boolean
}

export function UsersFilters({
  username,
  status,
  serviceId,
  onUsernameChange,
  onStatusChange,
  onServiceChange,
  services,
  isLoadingServices,
}: UsersFiltersProps) {
  const [localUsername, setLocalUsername] = useState(username)

  useEffect(() => {
    setLocalUsername(username)
  }, [username])

  return (
    <div className='flex flex-col gap-3 rounded-md border p-4 sm:flex-row sm:items-end sm:justify-between'>
      <div className='grid flex-1 gap-3 sm:grid-cols-3 sm:gap-4'>
        <div className='flex flex-col gap-1'>
          <label className='text-sm font-medium text-muted-foreground'>Username</label>
          <div className='relative'>
            <Search className='text-muted-foreground absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2' />
            <Input
              placeholder='Search username...'
              className='pl-9'
              value={localUsername}
              onChange={(event) => {
                const next = event.target.value
                setLocalUsername(next)
                onUsernameChange(next)
              }}
            />
          </div>
        </div>
        <div className='flex flex-col gap-1'>
          <label className='text-sm font-medium text-muted-foreground'>Service</label>
          <Select
            value={serviceId !== undefined ? String(serviceId) : ''}
            onValueChange={(value) => {
              if (value === '') {
                onServiceChange(undefined)
              } else {
                onServiceChange(Number(value))
              }
            }}
            disabled={isLoadingServices}
          >
            <SelectTrigger>
              <SelectValue placeholder='All services' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value=''>All services</SelectItem>
              {services.map((service) => (
                <SelectItem key={service.value} value={String(service.value)}>
                  {service.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className='flex flex-col gap-1'>
          <label className='text-sm font-medium text-muted-foreground'>Status</label>
          <Select
            value={status ?? ''}
            onValueChange={(value) => {
              if (value === '') {
                onStatusChange(undefined)
              } else {
                onStatusChange(value as 'active' | 'disabled')
              }
            }}
          >
            <SelectTrigger>
              <SelectValue placeholder='All statuses' />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value=''>All statuses</SelectItem>
              <SelectItem value='active'>Active</SelectItem>
              <SelectItem value='disabled'>Disabled</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      <div>
        <Button
          variant='ghost'
          onClick={() => {
            setLocalUsername('')
            onUsernameChange('')
            onStatusChange(undefined)
            onServiceChange(undefined)
          }}
        >
          Reset filters
        </Button>
      </div>
    </div>
  )
}
