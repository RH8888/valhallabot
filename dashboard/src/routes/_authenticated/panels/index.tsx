import z from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { PanelsList } from '@/features/panels'
import { PANEL_TYPES } from '@/features/panels/constants'

const panelsSearchSchema = z.object({
  page: z.number().optional().catch(1),
  pageSize: z.number().optional().catch(10),
  name: z.string().optional().catch(''),
  panelType: z
    .array(z.enum(PANEL_TYPES.map((type) => type.value) as [string, ...string[]]))
    .optional()
    .catch([]),
})

export const Route = createFileRoute('/_authenticated/panels/')({
  validateSearch: panelsSearchSchema,
  component: PanelsList,
})
