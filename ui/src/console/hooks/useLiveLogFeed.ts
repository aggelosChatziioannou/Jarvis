import { useCallback, useEffect, useRef, useState } from 'react'
import type { LogEntry } from '@/console/types/logs'
import { makeLogEntry, pickTemplate, seedLogs } from '@/console/data/logsMock'
import { capBuffer } from '@/console/lib/logsLogic'

const MAX_BUFFER = 500

export function useLiveLogFeed(paused: boolean) {
  const [logs, setLogs] = useState<LogEntry[]>(() => seedLogs(40, Date.now()))
  const timer = useRef<number | null>(null)

  useEffect(() => {
    if (paused) return
    let cancelled = false
    const tick = () => {
      if (cancelled) return
      setLogs((prev) => capBuffer([...prev, makeLogEntry(Date.now(), pickTemplate())], MAX_BUFFER))
      const delay = 350 + Math.random() * 900
      timer.current = window.setTimeout(tick, delay)
    }
    timer.current = window.setTimeout(tick, 600)
    return () => {
      cancelled = true
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [paused])

  const clear = useCallback(() => setLogs([]), [])
  return { logs, clear }
}
