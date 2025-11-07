import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { Setting } from '@/lib/api/types'
import type { SettingMetadata } from '../settings-metadata'
import { SettingItem } from './setting-item'

type CategoryCardProps = {
  title: string
  description: string
  settings: Array<{ setting: Setting; metadata: SettingMetadata }>
  onEdit: (setting: Setting, metadata: SettingMetadata) => void
  onDelete: (setting: Setting, metadata: SettingMetadata) => void
}

export function SettingsCategoryCard({ title, description, settings, onEdit, onDelete }: CategoryCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className='space-y-6'>
        {settings.map(({ setting, metadata }) => (
          <SettingItem
            key={setting.key}
            setting={setting}
            metadata={metadata}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        ))}
      </CardContent>
    </Card>
  )
}
