import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from './client'
import { agentsKeys } from './query-keys'
import type { Agent, AgentCreate, AgentUpdate } from './types'

export async function fetchAgents() {
  const response = await apiClient.get<Agent[]>('/admin/agents')
  return response.data
}

export async function fetchAgent(agentId: number) {
  const response = await apiClient.get<Agent>(`/admin/agents/${agentId}`)
  return response.data
}

export async function createAgent(payload: AgentCreate) {
  const response = await apiClient.post<Agent>('/admin/agents', payload)
  return response.data
}

export async function updateAgent(agentId: number, payload: AgentUpdate) {
  const response = await apiClient.put<Agent>(`/admin/agents/${agentId}`, payload)
  return response.data
}

export async function deleteAgent(agentId: number) {
  await apiClient.delete(`/admin/agents/${agentId}`)
}

export function useAgentsQuery() {
  return useQuery({
    queryKey: agentsKeys.lists(),
    queryFn: fetchAgents,
  })
}

export function useAgentQuery(agentId: number, enabled = true) {
  return useQuery({
    queryKey: agentsKeys.detail(agentId),
    queryFn: () => fetchAgent(agentId),
    enabled,
  })
}

export function useCreateAgentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createAgent,
    onSuccess: (agent) => {
      toast.success('Agent created successfully')
      queryClient.invalidateQueries({ queryKey: agentsKeys.lists() })
      queryClient.setQueryData(agentsKeys.detail(agent.id), agent)
    },
  })
}

export function useUpdateAgentMutation(agentId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AgentUpdate) => updateAgent(agentId, payload),
    onSuccess: (agent) => {
      toast.success('Agent updated successfully')
      queryClient.invalidateQueries({ queryKey: agentsKeys.lists() })
      queryClient.setQueryData(agentsKeys.detail(agent.id), agent)
    },
  })
}

export function useDeleteAgentMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteAgent,
    onSuccess: (_, agentId) => {
      toast.success('Agent deleted successfully')
      queryClient.invalidateQueries({ queryKey: agentsKeys.lists() })
      queryClient.removeQueries({ queryKey: agentsKeys.detail(agentId) })
    },
  })
}
