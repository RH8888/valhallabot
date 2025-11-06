export type Role = 'admin' | 'super_admin' | 'agent'

export interface Identity {
  role: Role
  agent_id: number | null
  agent_name: string | null
}
