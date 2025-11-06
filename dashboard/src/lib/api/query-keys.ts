import type { UserListRequest } from './types'

export const panelsKeys = {
  all: ['panels'] as const,
  lists: () => [...panelsKeys.all, 'list'] as const,
  detail: (id: number) => [...panelsKeys.all, 'detail', id] as const,
}

export const agentsKeys = {
  all: ['agents'] as const,
  lists: () => [...agentsKeys.all, 'list'] as const,
  detail: (id: number) => [...agentsKeys.all, 'detail', id] as const,
}

export const servicesKeys = {
  all: ['services'] as const,
  lists: () => [...servicesKeys.all, 'list'] as const,
  detail: (id: number) => [...servicesKeys.all, 'detail', id] as const,
}

export const settingsKeys = {
  all: ['settings'] as const,
  lists: () => [...settingsKeys.all, 'list'] as const,
  detail: (key: string) => [...settingsKeys.all, 'detail', key] as const,
}

export const usersKeys = {
  all: ['users'] as const,
  list: (input: UserListRequest) => [...usersKeys.all, 'list', input] as const,
  detail: (username: string, ownerId?: number | null) =>
    [...usersKeys.all, 'detail', username, ownerId ?? null] as const,
  usage: (username: string, ownerId?: number | null) =>
    [...usersKeys.all, 'usage', username, ownerId ?? null] as const,
}
