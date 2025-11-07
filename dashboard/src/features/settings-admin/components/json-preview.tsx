import { useMemo } from 'react'

function escapeHtml(value: string) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function highlightJson(value: string) {
  const escaped = escapeHtml(value)
  const pattern = /("(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g

  return escaped.replace(pattern, (match) => {
    let className = 'text-foreground'

    if (/^"/.test(match)) {
      className = match.endsWith(':') ? 'text-sky-500' : 'text-emerald-500'
    } else if (/true|false/.test(match)) {
      className = 'text-orange-500'
    } else if (/null/.test(match)) {
      className = 'text-purple-500'
    } else {
      className = 'text-amber-500'
    }

    return `<span class="${className}">${match}</span>`
  })
}

type JsonPreviewProps = {
  value: string
  isValid: boolean
}

export function JsonPreview({ value, isValid }: JsonPreviewProps) {
  const highlighted = useMemo(() => {
    if (!isValid) return null
    try {
      const formatted = JSON.stringify(JSON.parse(value), null, 2)
      return highlightJson(formatted)
    } catch (_error) {
      return null
    }
  }, [isValid, value])

  if (!isValid) {
    return (
      <div className='text-muted-foreground text-sm'>
        Provide valid JSON to see a formatted preview.
      </div>
    )
  }

  if (!highlighted) {
    return null
  }

  return (
    <pre
      className='bg-muted max-h-64 overflow-auto rounded-md border p-3 text-left text-sm font-mono leading-6'
      dangerouslySetInnerHTML={{ __html: highlighted }}
    />
  )
}
