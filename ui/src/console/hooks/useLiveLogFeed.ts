import { useCallback, useEffect, useRef, useState } from 'react'
import type { LogEntry } from '@/console/types/logs'
import { makeLogEntry, pickTemplate, seedLogs } from '@/console/data/logsMock'
import { capBuffer } from '@/console/lib/logsLogic'
import { api, openLogStream } from '@/console/services/seam'
import { toLogEntry } from '@/console/lib/logMap'

const MAX_BUFFER = 500

/**
 * Live log feed for the console.
 *
 * Live mode: subscribes to the daemon's /ws/logs (which backfills the last ~100
 * entries on connect, then streams). Backend payloads are mapped to console
 * LogEntry shape; duplicates (e.g. re-sent backfill on reconnect) are dropped.
 *
 * Demo mode (fail-open): if the daemon is unreachable, falls back to the
 * synthetic generator so the page stays alive and screenshotable.
 *
 * `paused` freezes ingestion in both modes; `clear` empties the view.
 */
export function useLiveLogFeed(paused: boolean) {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const pausedRef = useRef(paused)
  pausedRef.current = paused

  useEffect(() => {
    let cancelled = false
    let stopStream: (() => void) | null = null
    let demoTimer: number | null = null

    const append = (entry: LogEntry) => {
      if (cancelled || pausedRef.current) return
      setLogs((prev) =>
        prev.some((l) => l.id === entry.id) ? prev : capBuffer([...prev, entry], MAX_BUFFER),
      )
    }

    const startLive = () => {
      if (cancelled) return
      stopStream = openLogStream((p) => append(toLogEntry(p, Date.now())))
    }

    const startDemo = () => {
      if (cancelled) return
      setLogs(seedLogs(40, Date.now()))
      const tick = () => {
        if (cancelled) return
        if (!pausedRef.current) {
          setLogs((prev) => capBuffer([...prev, makeLogEntry(Date.now(), pickTemplate())], MAX_BUFFER))
        }
        demoTimer = window.setTimeout(tick, 350 + Math.random() * 900)
      }
      demoTimer = window.setTimeout(tick, 600)
    }

    // Probe the daemon; live if reachable, demo otherwise.
    api
      .health()
      .then(() => {
        if (!cancelled) startLive()
      })
      .catch(() => {
        if (!cancelled) startDemo()
      })

    return () => {
      cancelled = true
      if (stopStream) stopStream()
      if (demoTimer) window.clearTimeout(demoTimer)
    }
  }, [])

  const clear = useCallback(() => setLogs([]), [])
  return { logs, clear }
}
