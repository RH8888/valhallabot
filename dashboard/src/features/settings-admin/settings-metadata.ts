import type { Setting } from '@/lib/api/types'

export type SettingValueType = 'string' | 'number' | 'json'

export interface SettingCategory {
  id: string
  title: string
  description: string
}

export interface SettingMetadata {
  key: string
  label: string
  description: string
  type: SettingValueType
  category: SettingCategory
  critical?: boolean
}

const CATEGORY_DEFINITIONS: Record<string, SettingCategory> = {
  emergency: {
    id: 'emergency',
    title: 'Emergency controls',
    description:
      'Runtime kill switches and hard stops that immediately change cluster-wide behaviour.',
  },
  notifications: {
    id: 'notifications',
    title: 'Notifications & messaging',
    description: 'Delivery channels, templates, and throttles for outbound communication.',
  },
  automation: {
    id: 'automation',
    title: 'Automation & jobs',
    description: 'Task scheduling, worker coordination, and automation guardrails.',
  },
  limits: {
    id: 'limits',
    title: 'Limits & quotas',
    description: 'System-wide quotas, thresholds, and rate limiting policies.',
  },
  security: {
    id: 'security',
    title: 'Security & access',
    description: 'Keys, authentication toggles, and other access restrictions.',
  },
  experience: {
    id: 'experience',
    title: 'Experience & presentation',
    description: 'Settings that affect look, feel, and runtime feature exposure.',
  },
  integrations: {
    id: 'integrations',
    title: 'Integrations & webhooks',
    description: 'External system hooks, partner endpoints, and sync controls.',
  },
  observability: {
    id: 'observability',
    title: 'Observability & telemetry',
    description: 'Logging, metrics, alerting, and insight capture policies.',
  },
  data: {
    id: 'data',
    title: 'Data management',
    description: 'Retention windows, export policies, and storage behaviours.',
  },
  billing: {
    id: 'billing',
    title: 'Billing & monetisation',
    description: 'Plan enforcement, pricing multipliers, and billing guards.',
  },
  general: {
    id: 'general',
    title: 'Core configuration',
    description: 'Baseline application configuration that applies across the platform.',
  },
}

const CATEGORY_KEYWORDS: Array<[string, keyof typeof CATEGORY_DEFINITIONS]> = [
  ['emergency', 'emergency'],
  ['kill', 'emergency'],
  ['panic', 'emergency'],
  ['shutdown', 'emergency'],
  ['maintenance', 'emergency'],
  ['alert', 'notifications'],
  ['notify', 'notifications'],
  ['email', 'notifications'],
  ['webhook', 'integrations'],
  ['slack', 'integrations'],
  ['discord', 'integrations'],
  ['queue', 'automation'],
  ['job', 'automation'],
  ['worker', 'automation'],
  ['limit', 'limits'],
  ['quota', 'limits'],
  ['threshold', 'limits'],
  ['rate', 'limits'],
  ['timeout', 'limits'],
  ['auth', 'security'],
  ['token', 'security'],
  ['secret', 'security'],
  ['password', 'security'],
  ['theme', 'experience'],
  ['feature', 'experience'],
  ['ui', 'experience'],
  ['ux', 'experience'],
  ['metric', 'observability'],
  ['telemetry', 'observability'],
  ['log', 'observability'],
  ['trace', 'observability'],
  ['retention', 'data'],
  ['archive', 'data'],
  ['storage', 'data'],
  ['export', 'data'],
  ['billing', 'billing'],
  ['price', 'billing'],
  ['plan', 'billing'],
  ['invoice', 'billing'],
]

const KEY_OVERRIDES: Record<string, Partial<Omit<SettingMetadata, 'key' | 'category'>>> = {
  emergency_shutdown: {
    label: 'Emergency shutdown',
    description: 'Forcefully pause all outbound activity immediately.',
    critical: true,
  },
  emergency_mode: {
    label: 'Emergency broadcast mode',
    description:
      'Enables heightened safety posture and emergency messaging to all tenants.',
    critical: true,
  },
  maintenance_mode: {
    label: 'Maintenance mode',
    description: 'Displays maintenance messaging and blocks new workflows.',
    critical: true,
  },
  notifications_global_template: {
    label: 'Global notification template',
    description: 'Default Markdown/HTML template for outbound notifications.',
    type: 'json',
  },
  notifications_throttle_seconds: {
    label: 'Notification throttle (seconds)',
    description: 'Minimum number of seconds to wait before resending notifications.',
    type: 'number',
  },
  max_user_limit: {
    label: 'User hard limit',
    description: 'Maximum number of user accounts allowed in this cluster.',
    type: 'number',
  },
  usage_retention_policy: {
    label: 'Usage retention policy',
    description: 'Defines the retention policy for usage analytics.',
    type: 'json',
  },
  billing_price_multiplier: {
    label: 'Billing price multiplier',
    description: 'Applies a multiplier to all pay-as-you-go billing calculations.',
    type: 'number',
  },
}

const TYPE_KEYWORDS: Array<[RegExp, SettingValueType]> = [
  [/json/i, 'json'],
  [/payload/i, 'json'],
  [/template/i, 'json'],
  [/config/i, 'json'],
  [/(count|limit|threshold|timeout|ttl|duration|seconds|minutes|hours|days|max|min|ratio|percentage|port|bytes|size|multiplier|interval)/i, 'number'],
]

const UPPERCASE_TOKENS = new Set(['api', 'ui', 'ux', 'sla', 'ttl', 'qa'])

export function deriveSettingMetadata(setting: Setting): SettingMetadata {
  const key = setting.key
  const override = KEY_OVERRIDES[key]
  const normalized = key.toLowerCase()

  const type = override?.type ?? inferType(normalized)
  const category = inferCategory(normalized)
  const label = override?.label ?? toTitleCase(key)
  const description = override?.description ?? buildFallbackDescription(label)
  const critical = override?.critical ?? isCriticalKey(normalized)

  return {
    key,
    label,
    description,
    type,
    category,
    critical,
  }
}

function inferType(key: string): SettingValueType {
  for (const [matcher, type] of TYPE_KEYWORDS) {
    if (matcher.test(key)) {
      return type
    }
  }
  return 'string'
}

function inferCategory(key: string): SettingCategory {
  for (const [keyword, category] of CATEGORY_KEYWORDS) {
    if (key.includes(keyword)) {
      return CATEGORY_DEFINITIONS[category]
    }
  }

  const prefix = key.split(/[.:_-]/)[0]
  if (prefix && CATEGORY_DEFINITIONS[prefix as keyof typeof CATEGORY_DEFINITIONS]) {
    return CATEGORY_DEFINITIONS[prefix as keyof typeof CATEGORY_DEFINITIONS]
  }

  return CATEGORY_DEFINITIONS.general
}

function toTitleCase(key: string): string {
  return key
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => {
      const token = part.toLowerCase()
      if (UPPERCASE_TOKENS.has(token)) {
        return token.toUpperCase()
      }
      return token.charAt(0).toUpperCase() + token.slice(1)
    })
    .join(' ')
}

function buildFallbackDescription(label: string) {
  const lower = label.toLowerCase()
  return `Configure how ${lower} behaves across the platform.`
}

function isCriticalKey(key: string) {
  return /emergency|shutdown|panic|kill|maintenance/.test(key)
}
