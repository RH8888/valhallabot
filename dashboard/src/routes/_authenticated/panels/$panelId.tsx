import { createFileRoute } from '@tanstack/react-router'
import { PanelDetail } from '@/features/panels/panel-detail'

export const Route = createFileRoute('/_authenticated/panels/$panelId')({
  component: PanelDetail,
})
