import { useState } from 'react'
import { Calendar as CalendarIcon, Check, RotateCcw, X } from 'lucide-react'
import { format, parseISO } from 'date-fns'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

type InlineDateEditorProps = {
  label: string
  value: string | null
  onSave: (value: string | null) => Promise<void> | void
  isSaving?: boolean
}

function parseDate(value: string | null): Date | undefined {
  if (!value) return undefined
  try {
    return parseISO(value)
  } catch (_error) {
    return undefined
  }
}

export function InlineDateEditor({ label, value, onSave, isSaving = false }: InlineDateEditorProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<Date | null>(null)

  const parsedValue = parseDate(value)
  const currentDraft = draft ?? parsedValue
  const formatted = parsedValue ? format(parsedValue, 'PPP') : 'No expiry set'

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen)
    if (nextOpen) {
      setDraft(parsedValue ?? null)
    } else {
      setDraft(null)
    }
  }

  const handleSave = async (next: Date | null | undefined) => {
    const payload = next ? next.toISOString() : null
    try {
      await onSave(payload)
      setOpen(false)
      setDraft(null)
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : `Unable to update ${label.toLowerCase()}. Please try again.`
      toast.error(message)
    }
  }

  const handleClear = () => {
    setDraft(null)
  }

  return (
    <div className='space-y-1'>
      <div className='flex items-start justify-between gap-2'>
        <div>
          <div className='font-medium leading-tight'>{formatted}</div>
          <p className='text-xs text-muted-foreground'>{label}</p>
        </div>
        <Popover open={open} onOpenChange={handleOpenChange}>
          <PopoverTrigger asChild>
            <Button variant='ghost' size='icon' className='h-7 w-7'>
              <CalendarIcon className='h-4 w-4' />
              <span className='sr-only'>Edit {label}</span>
            </Button>
          </PopoverTrigger>
          <PopoverContent className='w-[300px] space-y-3 p-3'>
            <div className='space-y-1 px-1'>
              <p className='text-sm font-medium leading-none'>Adjust {label.toLowerCase()}</p>
              <p className='text-xs text-muted-foreground'>
                Select a new date or clear the expiry to keep the agent active indefinitely.
              </p>
            </div>
            <Calendar
              mode='single'
              selected={currentDraft ?? undefined}
              onSelect={(date) => setDraft(date ?? null)}
              initialFocus
            />
            <div className='flex justify-between gap-2'>
              <Button
                variant='outline'
                size='sm'
                onClick={handleClear}
                disabled={isSaving}
                className='gap-1'
              >
                <RotateCcw className='h-4 w-4' />
                Clear expiry
              </Button>
              <div className='flex gap-2'>
                <Button
                  variant='ghost'
                  size='sm'
                  onClick={() => setOpen(false)}
                  disabled={isSaving}
                  className='gap-1'
                >
                  <X className='h-4 w-4' />
                  Cancel
                </Button>
                <Button
                  size='sm'
                  onClick={() => handleSave(draft)}
                  disabled={isSaving}
                  className='gap-1'
                >
                  <Check className='h-4 w-4' />
                  Save
                </Button>
              </div>
            </div>
          </PopoverContent>
        </Popover>
      </div>
      <p className='text-xs text-muted-foreground'>
        Expiry is evaluated daily. Clearing the expiry keeps the agent active until quota is exhausted.
      </p>
    </div>
  )
}
