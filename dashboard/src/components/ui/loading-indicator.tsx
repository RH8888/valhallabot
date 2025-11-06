import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface LoadingIndicatorProps {
  label?: string
  className?: string
  inline?: boolean
  size?: number
}

export function LoadingIndicator({
  label = 'Loading…',
  className,
  inline = false,
  size = 20,
}: LoadingIndicatorProps) {
  const content = (
    <span className={cn('flex items-center gap-2 text-sm text-muted-foreground', className)}>
      <Loader2 className='animate-spin' style={{ width: size, height: size }} />
      {label ? <span>{label}</span> : null}
    </span>
  )

  if (inline) {
    return content
  }

  return (
    <div className='flex w-full items-center justify-center py-8'>
      {content}
    </div>
  )
}

interface LoadingOverlayProps {
  label?: string
  className?: string
}

export function LoadingOverlay({ label, className }: LoadingOverlayProps) {
  return (
    <div className={cn('flex min-h-[120px] items-center justify-center', className)}>
      <LoadingIndicator label={label} inline />
    </div>
  )
}
