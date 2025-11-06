import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from './client'
import { panelsKeys } from './query-keys'
import type { Panel, PanelCreate, PanelDisableResult, PanelUpdate } from './types'

export async function fetchPanels() {
  const response = await apiClient.get<Panel[]>('/admin/panels')
  return response.data
}

export async function fetchPanel(panelId: number) {
  const response = await apiClient.get<Panel>(`/admin/panels/${panelId}`)
  return response.data
}

export async function createPanel(payload: PanelCreate) {
  const response = await apiClient.post<Panel>('/admin/panels', payload)
  return response.data
}

export async function updatePanel(panelId: number, payload: PanelUpdate) {
  const response = await apiClient.put<Panel>(`/admin/panels/${panelId}`, payload)
  return response.data
}

export async function deletePanel(panelId: number) {
  await apiClient.delete(`/admin/panels/${panelId}`)
}

export async function disablePanel(panelId: number) {
  const response = await apiClient.post<PanelDisableResult>(
    `/admin/panels/${panelId}/disable`
  )
  return response.data
}

export function usePanelsQuery() {
  return useQuery({
    queryKey: panelsKeys.lists(),
    queryFn: fetchPanels,
  })
}

export function usePanelQuery(panelId: number, enabled = true) {
  return useQuery({
    queryKey: panelsKeys.detail(panelId),
    queryFn: () => fetchPanel(panelId),
    enabled,
  })
}

export function useCreatePanelMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createPanel,
    onSuccess: (panel) => {
      toast.success('Panel created successfully')
      queryClient.invalidateQueries({ queryKey: panelsKeys.lists() })
      queryClient.setQueryData(panelsKeys.detail(panel.id), panel)
    },
  })
}

export function useUpdatePanelMutation(panelId?: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: PanelUpdate) => {
      if (panelId === undefined) {
        throw new Error('Panel id is required to update a panel.')
      }
      return updatePanel(panelId, payload)
    },
    onSuccess: (panel) => {
      toast.success('Panel updated successfully')
      queryClient.invalidateQueries({ queryKey: panelsKeys.lists() })
      queryClient.setQueryData(panelsKeys.detail(panel.id), panel)
    },
  })
}

export function useDeletePanelMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deletePanel,
    onSuccess: (_, panelId) => {
      toast.success('Panel deleted successfully')
      queryClient.invalidateQueries({ queryKey: panelsKeys.lists() })
      queryClient.removeQueries({ queryKey: panelsKeys.detail(panelId) })
    },
  })
}

export function useDisablePanelMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: disablePanel,
    onSuccess: (_, panelId) => {
      queryClient.invalidateQueries({ queryKey: panelsKeys.lists() })
      queryClient.invalidateQueries({ queryKey: panelsKeys.detail(panelId) })
    },
  })
}
