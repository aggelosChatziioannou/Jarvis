import { useEffect, useState } from 'react'
import { api, openStateStream, fetchVersion } from './seam'
import type { VoiceStatePayload } from './seam'
import { dashboardApi } from './dashboardApi'

export interface ConnectionInfo {
  /** Latest voice-state snapshot from the daemon, or null until first arrival. */
  state: VoiceStatePayload | null
  /** True once the daemon has answered (health ok or a state frame arrived). */
  connected: boolean
  /** App version string (without leading "v"); empty until fetched. */
  version: string
  /** Current outdoor temperature in °C from the weather service, or null. */
  tempC: number | null
}

/**
 * Subscribes the console shell to live daemon state + version.
 *
 * Fail-open: if the daemon never answers, `connected` stays false and the
 * StatusBar shows "Offline" rather than crashing. Reconnection is handled by
 * the underlying `openStateStream`.
 */
export function useConnection(): ConnectionInfo {
  const [state, setState] = useState<VoiceStatePayload | null>(null)
  const [connected, setConnected] = useState(false)
  const [version, setVersion] = useState('')
  const [tempC, setTempC] = useState<number | null>(null)

  useEffect(() => {
    let alive = true

    fetchVersion().then((v) => {
      if (alive) setVersion(v.version)
    })
    api
      .health()
      .then(() => {
        if (alive) setConnected(true)
      })
      .catch(() => {})

    const loadWeather = () =>
      dashboardApi
        .metrics()
        .then((m) => {
          if (alive) setTempC(m.weather?.temp_c ?? null)
        })
        .catch(() => {})
    void loadWeather()
    const weatherTimer = window.setInterval(loadWeather, 15 * 60 * 1000)

    const stop = openStateStream((s) => {
      if (!alive) return
      setState(s)
      setConnected(true)
    })

    return () => {
      alive = false
      window.clearInterval(weatherTimer)
      stop()
    }
  }, [])

  return { state, connected, version, tempC }
}
