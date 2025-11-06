import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { toast } from 'sonner'
import { apiClient } from './client'
import { servicesKeys } from './query-keys'
import type {
  Service,
  ServiceCreate,
  ServicePanelsPayload,
  ServicePanelsResponse,
  ServiceUpdate,
} from './types'

export async function fetchServices() {
  const response = await apiClient.get<Service[]>('/admin/services')
  return response.data
}

export async function fetchService(serviceId: number) {
  const response = await apiClient.get<Service>(`/admin/services/${serviceId}`)
  return response.data
}

export async function createService(payload: ServiceCreate) {
  const response = await apiClient.post<Service>('/admin/services', payload)
  return response.data
}

export async function updateService(serviceId: number, payload: ServiceUpdate) {
  const response = await apiClient.put<Service>(`/admin/services/${serviceId}`, payload)
  return response.data
}

export async function deleteService(serviceId: number) {
  await apiClient.delete(`/admin/services/${serviceId}`)
}

export async function fetchServicePanels(serviceId: number) {
  const response = await apiClient.get<ServicePanelsResponse>(
    `/admin/services/${serviceId}/panels`
  )
  return response.data
}

export async function updateServicePanels(
  serviceId: number,
  payload: ServicePanelsPayload
) {
  const response = await apiClient.put<ServicePanelsResponse>(
    `/admin/services/${serviceId}/panels`,
    payload
  )
  return response.data
}

export function useServicesQuery() {
  return useQuery({
    queryKey: servicesKeys.lists(),
    queryFn: fetchServices,
  })
}

export function useServiceQuery(serviceId: number, enabled = true) {
  return useQuery({
    queryKey: servicesKeys.detail(serviceId),
    queryFn: () => fetchService(serviceId),
    enabled,
  })
}

export function useServicePanelsQuery(serviceId: number, enabled = true) {
  return useQuery({
    queryKey: servicesKeys.panels(serviceId),
    queryFn: () => fetchServicePanels(serviceId),
    enabled,
  })
}

export function useCreateServiceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createService,
    onSuccess: (service) => {
      toast.success('Service created successfully')
      queryClient.invalidateQueries({ queryKey: servicesKeys.lists() })
      queryClient.setQueryData(servicesKeys.detail(service.id), service)
    },
  })
}

export function useUpdateServiceMutation(serviceId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ServiceUpdate) => updateService(serviceId, payload),
    onSuccess: (service) => {
      toast.success('Service updated successfully')
      queryClient.invalidateQueries({ queryKey: servicesKeys.lists() })
      queryClient.setQueryData(servicesKeys.detail(service.id), service)
    },
  })
}

export function useUpdateServicePanelsMutation(serviceId?: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ServicePanelsPayload) => {
      if (serviceId === undefined) {
        throw new Error('Service id is required to update panels.')
      }
      return updateServicePanels(serviceId, payload)
    },
    onSuccess: (result) => {
      toast.success('Service panels updated successfully')
      queryClient.invalidateQueries({ queryKey: servicesKeys.lists() })
      queryClient.setQueryData(servicesKeys.detail(result.service.id), result.service)
      queryClient.setQueryData(servicesKeys.panels(result.service.id), result)
    },
  })
}

export function useDeleteServiceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteService,
    onSuccess: (_, serviceId) => {
      toast.success('Service deleted successfully')
      queryClient.invalidateQueries({ queryKey: servicesKeys.lists() })
      queryClient.removeQueries({ queryKey: servicesKeys.detail(serviceId) })
      queryClient.removeQueries({ queryKey: servicesKeys.panels(serviceId) })
    },
    onError: (error: unknown) => {
      let message = 'Failed to delete service. Please try again.'
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string') {
          message = detail
        } else if (Array.isArray(detail)) {
          message = detail.join('\n')
        }
      }
      toast.error(message)
    },
  })
}
