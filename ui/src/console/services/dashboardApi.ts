// Dashboard fetchers: real system metrics + service status.

const BASE =
  typeof window !== 'undefined' && window.location.port === '38130'
    ? ''
    : 'http://127.0.0.1:38130'

async function j<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

export interface Weather {
  temp_c: number | null
  description: string
  place: string
}

export interface SystemMetrics {
  uptime_sec: number
  cpu_percent: number | null
  ram: { used: number; total: number; percent: number } | null
  gpu: { mem_used_mb: number; mem_total_mb: number; util_percent: number } | null
  models: string[]
  weather: Weather | null
}

export interface ServiceStatus {
  id: string
  name: string
  enabled: boolean
  connected: boolean
  detail: string
  count?: number
}

export const dashboardApi = {
  metrics: () => j<SystemMetrics>('/api/system/metrics'),
  services: () => j<ServiceStatus[]>('/api/services/status'),
}
