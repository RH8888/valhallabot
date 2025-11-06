export const PANEL_TYPES = [
  { label: 'Marzneshin', value: 'marzneshin' },
  { label: 'Marzban', value: 'marzban' },
  { label: 'Rebecca', value: 'rebecca' },
  { label: 'Sanaei', value: 'sanaei' },
  { label: 'Pasarguard', value: 'pasarguard' },
] as const

type PanelTypeTuple = typeof PANEL_TYPES

export type PanelTypeValue = PanelTypeTuple[number]['value']
