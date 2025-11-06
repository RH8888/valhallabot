import { useState } from 'react'
import { Check, PencilLine, X } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

type InlineNumberEditorProps = {
  label: string
  value: number
  helperText?: string
  formatValue?: (value: number) => string
  onSave: (value: number) => Promise<void> | void
  isSaving?: boolean
  min?: number
  step?: number
  unit?: string
}

export function InlineNumberEditor({
  label,
  value,
  helperText,
  formatValue,
  onSave,
  isSaving = false,
  min,
  step,
  unit,
}: InlineNumberEditorProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<string | null>(null)

  const displayValue = formatValue ? formatValue(value) : value.toLocaleString()
  const currentDraft = draft ?? value.toString()

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen)
    if (nextOpen) {
      setDraft(value.toString())
    } else {
      setDraft(null)
    }
  }

  const handleSave = async () => {
    const parsed = Number(currentDraft)
    if (!Number.isFinite(parsed)) {
      toast.error(`Enter a valid number for ${label.toLowerCase()}.`)
      return
    }

    try {
      await onSave(parsed)
      setOpen(false)
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : `Unable to update ${label.toLowerCase()}. Please try again.`
      toast.error(message)
    }
  }

  return (
    <div className='space-y-1'>
      <div className='flex items-start justify-between gap-2'>
        <div>
          <div className='font-medium leading-tight'>{displayValue}</div>
          <p className='text-xs text-muted-foreground'>{label}</p>
        </div>
        <Popover open={open} onOpenChange={handleOpenChange}>
          <PopoverTrigger asChild>
            <Button variant='ghost' size='icon' className='h-7 w-7'>
              <PencilLine className='h-4 w-4' />
              <span className='sr-only'>Edit {label}</span>
            </Button>
          </PopoverTrigger>
          <PopoverContent align='end' className='w-60 space-y-3'>
            <div className='space-y-1'>
              <p className='text-sm font-medium leading-none'>Edit {label.toLowerCase()}</p>
              <p className='text-xs text-muted-foreground'>
                Enter a new value and save to apply changes immediately.
              </p>
            </div>
            <Input
              type='number'
              value={currentDraft}
              min={min}
              step={step}
              onChange={(event) => setDraft(event.target.value)}
              autoFocus
            />
            {unit ? (
              <p className='text-xs text-muted-foreground'>Values are stored in {unit}.</p>
            ) : null}
            {helperText ? (
              <p className='text-xs text-muted-foreground'>{helperText}</p>
            ) : null}
            <div className='flex justify-end gap-2'>
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
                onClick={handleSave}
                disabled={isSaving}
                className={cn('gap-1')}
              >
                <Check className='h-4 w-4' />
                Save
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      </div>
      {helperText ? (
        <p className='text-xs text-muted-foreground'>{helperText}</p>
      ) : null}
    </div>
  )
}
