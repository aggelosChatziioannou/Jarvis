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
  /** Live activity (e.g. Spotify playing, Gmail has unread) for glows. */
  active?: boolean
  // Spotify now-playing extras (present only on the spotify entry):
  title?: string
  artist?: string
  image_url?: string | null
  is_playing?: boolean
}

export const dashboardApi = {
  metrics: () => j<SystemMetrics>('/api/system/metrics'),
  services: () => j<ServiceStatus[]>('/api/services/status'),
}

export interface SpotifyControlResult {
  ok: boolean
  is_playing?: boolean
  reason?: string
}

export async function spotifyControl(op: 'playpause' | 'next' | 'prev'): Promise<SpotifyControlResult> {
  try {
    const r = await fetch(`${BASE}/api/spotify/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ op }),
    })
    if (!r.ok) return { ok: false, reason: `http ${r.status}` }
    return (await r.json()) as SpotifyControlResult
  } catch {
    return { ok: false, reason: 'network' }
  }
}
