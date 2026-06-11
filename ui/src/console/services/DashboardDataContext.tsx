import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { openStateStream } from './seam'
import type { VoiceStatePayload } from './seam'
import { dashboardApi } from './dashboardApi'
import type { SystemMetrics, ServiceStatus, MarketsPayload } from './dashboardApi'

export interface DashboardData {
  connected: boolean
  state: VoiceStatePayload | null
  metrics: SystemMetrics | null
  services: ServiceStatus[]
  markets: MarketsPayload | null
}

const POLL_MS = 5000

function useDashboardData(): DashboardData {
  const [connected, setConnected] = useState(false)
  const [state, setState] = useState<VoiceStatePayload | null>(null)
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null)
  const [services, setServices] = useState<ServiceStatus[]>([])
  const [markets, setMarkets] = useState<MarketsPayload | null>(null)
  const timer = useRef<number | null>(null)
  const lastMarkets = useRef(0)

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const m = await dashboardApi.metrics()
        if (alive) {
          setMetrics(m)
          setConnected(true)
        }
      } catch {
        /* keep last */
      }
      try {
        const s = await dashboardApi.services()
        if (alive) setServices(s)
      } catch {
        /* keep last */
      }
      // Markets refresh every ~60s (server caches at the same cadence).
      if (Date.now() - lastMarkets.current > 55_000) {
        lastMarkets.current = Date.now()
        try {
          const mk = await dashboardApi.markets()
          if (alive) setMarkets(mk)
        } catch {
          /* keep last */
        }
      }
      if (alive) timer.current = window.setTimeout(poll, POLL_MS)
    }
    void poll()
    const stop = openStateStream((s) => {
      if (!alive) return
      setState(s)
      setConnected(true)
    })
    return () => {
      alive = false
      if (timer.current) window.clearTimeout(timer.current)
      stop()
    }
  }, [])

  return { connected, state, metrics, services, markets }
}

const Ctx = createContext<DashboardData | null>(null)

export function DashboardDataProvider({ children }: { children: ReactNode }) {
  return <Ctx.Provider value={useDashboardData()}>{children}</Ctx.Provider>
}

export function useDashboardDataCtx(): DashboardData {
  const v = useContext(Ctx)
  if (!v) throw new Error('useDashboardDataCtx must be used within <DashboardDataProvider>')
  return v
}
