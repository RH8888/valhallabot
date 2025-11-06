import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from './client'
import { settingsKeys } from './query-keys'
import type { Setting, SettingValue } from './types'

export async function fetchSettings() {
  const response = await apiClient.get<Setting[]>('/admin/settings')
  return response.data
}

export async function fetchSetting(key: string) {
  const response = await apiClient.get<Setting>(`/admin/settings/${encodeURIComponent(key)}`)
  return response.data
}

export async function upsertSetting(key: string, payload: SettingValue) {
  const response = await apiClient.put<Setting>(`/admin/settings/${encodeURIComponent(key)}`, payload)
  return response.data
}

export async function deleteSetting(key: string) {
  await apiClient.delete(`/admin/settings/${encodeURIComponent(key)}`)
}

export function useSettingsQuery() {
  return useQuery({
    queryKey: settingsKeys.lists(),
    queryFn: fetchSettings,
  })
}

export function useSettingQuery(key: string, enabled = true) {
  return useQuery({
    queryKey: settingsKeys.detail(key),
    queryFn: () => fetchSetting(key),
    enabled,
  })
}

export function useUpsertSettingMutation(key: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: SettingValue) => upsertSetting(key, payload),
    onSuccess: (setting) => {
      toast.success('Setting saved successfully')
      queryClient.invalidateQueries({ queryKey: settingsKeys.lists() })
      queryClient.setQueryData(settingsKeys.detail(setting.key), setting)
    },
  })
}

export function useDeleteSettingMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteSetting,
    onSuccess: (_, key) => {
      toast.success('Setting removed successfully')
      queryClient.invalidateQueries({ queryKey: settingsKeys.lists() })
      queryClient.removeQueries({ queryKey: settingsKeys.detail(key) })
    },
  })
}
