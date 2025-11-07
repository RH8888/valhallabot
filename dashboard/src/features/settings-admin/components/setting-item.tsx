import { AlertTriangle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { Setting } from '@/lib/api/types'
import type { SettingMetadata, SettingValueType } from '../settings-metadata'

type SettingItemProps = {
  setting: Setting
  metadata: SettingMetadata
  onEdit: (setting: Setting, metadata: SettingMetadata) => void
  onDelete: (setting: Setting, metadata: SettingMetadata) => void
}

function getTypeLabel(type: SettingValueType) {
  switch (type) {
    case 'json':
      return 'JSON'
    case 'number':
      return 'Numeric'
    default:
      return 'Text'
  }
}

function isTruthy(value: string) {
  const normalized = value.trim().toLowerCase()
  return ['1', 'true', 'yes', 'enabled', 'on'].includes(normalized)
}

function formatValue(value: string, type: SettingValueType) {
  if (type === 'json') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2)
    } catch (_error) {
      return null
    }
  }
  if (type === 'number') {
    const parsed = Number(value)
    if (!Number.isNaN(parsed)) {
      return parsed.toString()
    }
  }
  return value
}

export function SettingItem({ setting, metadata, onEdit, onDelete }: SettingItemProps) {
  const displayValue = formatValue(setting.value, metadata.type)
  const hasCriticalWarning = Boolean(metadata.critical && isTruthy(setting.value))
  const isJsonInvalid = metadata.type === 'json' && displayValue === null

  return (
    <div className='flex flex-col gap-4 border-b pb-6 last:border-b-0 last:pb-0 md:flex-row md:items-start md:justify-between md:gap-6'>
      <div className='space-y-2'>
        <div className='flex flex-wrap items-center gap-2'>
          <h3 className='text-base font-semibold leading-tight'>{metadata.label}</h3>
          <Badge variant='secondary'>{getTypeLabel(metadata.type)}</Badge>
          {metadata.critical && (
            <Badge variant={hasCriticalWarning ? 'destructive' : 'outline'} className='flex items-center gap-1'>
              <AlertTriangle className='size-3' />
              {hasCriticalWarning ? 'Emergency active' : 'Critical flag'}
            </Badge>
          )}
        </div>
        <p className='text-sm text-muted-foreground'>{metadata.description}</p>
        <div className='font-mono text-xs text-muted-foreground'>Key: {setting.key}</div>
      </div>
      <div className='flex w-full flex-col gap-3 md:w-auto md:items-end'>
        <div
          className={cn(
            'w-full max-w-xl rounded-md border bg-muted p-3 font-mono text-sm text-left whitespace-pre-wrap md:w-[28rem]',
            metadata.type === 'json' && 'max-h-40 overflow-auto',
            isJsonInvalid && 'border-destructive text-destructive'
          )}
        >
          {metadata.type === 'json' ? (
            displayValue ? displayValue : 'Invalid JSON payload'
          ) : (
            displayValue || '—'
          )}
        </div>
        <div className='flex flex-wrap gap-2'>
          <Button size='sm' variant='outline' onClick={() => onEdit(setting, metadata)}>
            Edit
          </Button>
          <Button
            size='sm'
            variant='ghost'
            className='text-destructive hover:bg-destructive/10'
            onClick={() => onDelete(setting, metadata)}
          >
            Delete
          </Button>
        </div>
      </div>
    </div>
  )
}
