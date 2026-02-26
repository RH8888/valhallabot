export type UserRecord = {
  username: string;
  plan_limit_bytes: number;
  used_bytes: number;
  expire_at?: string | null;
  service_id?: number | null;
  disabled: boolean;
};

export type UsersResponse = {
  total: number;
  total_used_bytes?: number;
  users: UserRecord[];
};

export type ServiceRecord = {
  id: number;
  name: string;
};

export type SubscriptionResponse = {
  urls: string[];
  qr_data_uris: string[];
};

export type UserFormValues = {
  username: string;
  limitGb: string;
  durationDays: string;
  serviceId: string;
};
