export interface PanelBase {
  panel_url: string
  name: string
  panel_type?: string
  admin_username: string
  access_token: string
  template_username?: string | null
  sub_url?: string | null
}

export interface Panel extends PanelBase {
  id: number
  panel_type: string
  created_at: string
}

export type PanelCreate = PanelBase

export type PanelUpdate = Partial<Omit<PanelBase, 'panel_url'>> & {
  panel_url?: string | null
}

export interface PanelDisableResult {
  status?: string
  message?: string
  detail?: string | string[]
  errors?: string[]
  remote_errors?: string[]
  remote_cleanup?: Array<{
    target?: string
    ok?: boolean
    status?: string
    message?: string
  }>
}

export interface AgentBase {
  telegram_user_id: number
  name: string
  plan_limit_bytes: number
  expire_at?: string | null
  active?: boolean
  user_limit: number
  max_user_bytes: number
}

export interface Agent extends AgentBase {
  id: number
  created_at: string
  active: boolean
}

export type AgentCreate = AgentBase

export type AgentUpdate = Partial<Omit<AgentBase, 'telegram_user_id'>> & {
  expire_at?: string | null
}

export interface ServiceBase {
  name: string
}

export interface Service extends ServiceBase {
  id: number
  created_at: string
}

export type ServiceCreate = ServiceBase

export type ServiceUpdate = Partial<ServiceBase>

export interface Setting {
  key: string
  value: string
}

export interface SettingValue {
  value: string
}

export interface User {
  username: string
  plan_limit_bytes: number
  used_bytes: number
  expire_at: string | null
  service_id: number | null
  disabled: boolean
  access_key: string | null
  key_expires_at: string | null
}

export interface UserCreate {
  username: string
  limit_bytes: number
  duration_days: number
  service_id?: number | null
  owner_id?: number | null
}

export interface UserUpdate {
  limit_bytes?: number | null
  reset_used?: boolean
  renew_days?: number | null
  service_id?: number | null
  owner_id?: number | null
}

export interface UserListRequest {
  owner_id?: number | null
  offset?: number
  limit?: number
  search?: string | null
  service_id?: number | null
}

export interface UserListResponse {
  total: number
  users: User[]
}

export interface UsageRequest {
  owner_id?: number | null
}

export interface Usage {
  username: string
  used_bytes: number
  plan_limit_bytes: number
  expire_at: string | null
}
