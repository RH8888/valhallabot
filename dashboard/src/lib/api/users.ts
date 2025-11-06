import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from './client'
import { usersKeys } from './query-keys'
import type {
  Usage,
  UsageRequest,
  User,
  UserCreate,
  UserListRequest,
  UserListResponse,
  UserUpdate,
} from './types'

function normalizeUserListInput(input: UserListRequest = {}) {
  return {
    owner_id: input.owner_id ?? null,
    offset: input.offset ?? 0,
    limit: input.limit ?? 25,
    search: input.search ?? null,
    service_id: input.service_id ?? null,
  }
}

export async function listUsers(input: UserListRequest = {}) {
  const payload = normalizeUserListInput(input)
  const response = await apiClient.post<UserListResponse>('/users', payload)
  return response.data
}

export async function createUser(payload: UserCreate) {
  const response = await apiClient.post<User>('/users/create', payload)
  return response.data
}

export async function updateUser(username: string, payload: UserUpdate) {
  const response = await apiClient.patch<User>(`/users/${encodeURIComponent(username)}`, payload)
  return response.data
}

export async function toggleUser(username: string, disable = true, ownerId?: number | null) {
  await apiClient.delete(`/users/${encodeURIComponent(username)}`, {
    params: {
      disable,
      owner_id: ownerId ?? undefined,
    },
  })
}

export async function fetchUsage(username: string, input: UsageRequest = {}) {
  const response = await apiClient.post<Usage>(
    `/users/${encodeURIComponent(username)}/usage`,
    {
      owner_id: input.owner_id ?? null,
    }
  )
  return response.data
}

export function useUsersQuery(input: UserListRequest = {}) {
  const normalized = normalizeUserListInput(input)
  return useQuery({
    queryKey: usersKeys.list(normalized),
    queryFn: () => listUsers(normalized),
  })
}

export function useCreateUserMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      toast.success('User created successfully')
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
    },
  })
}

export function useUpdateUserMutation(username: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: UserUpdate) => updateUser(username, payload),
    onSuccess: (user) => {
      toast.success('User updated successfully')
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
      queryClient.invalidateQueries({
        predicate: (query) => {
          const [scope, type, key] = query.queryKey
          return (
            scope === 'users' &&
            type === 'usage' &&
            typeof key === 'string' &&
            key === user.username
          )
        },
      })
    },
  })
}

export function useToggleUserMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      username,
      disable,
      ownerId,
    }: {
      username: string
      disable?: boolean
      ownerId?: number | null
    }) => toggleUser(username, disable, ownerId),
    onSuccess: (_, variables) => {
      toast.success(
        variables.disable === false ? 'User enabled successfully' : 'User disabled successfully'
      )
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
    },
  })
}

export function useUsageQuery(username: string, input: UsageRequest = {}, enabled = true) {
  const ownerId = input.owner_id ?? null
  return useQuery({
    queryKey: usersKeys.usage(username, ownerId),
    queryFn: () => fetchUsage(username, { owner_id: ownerId }),
    enabled,
  })
}
