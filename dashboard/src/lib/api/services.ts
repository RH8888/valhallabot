import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from './client'
import { servicesKeys } from './query-keys'
import type { Service, ServiceCreate, ServiceUpdate } from './types'

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

export function useDeleteServiceMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteService,
    onSuccess: (_, serviceId) => {
      toast.success('Service deleted successfully')
      queryClient.invalidateQueries({ queryKey: servicesKeys.lists() })
      queryClient.removeQueries({ queryKey: servicesKeys.detail(serviceId) })
    },
  })
}
