import type { LogEntry, LogLevel, LogSource } from '@/console/types/logs'

export interface LogFilter {
  levels: Set<LogLevel>
  sources: Set<LogSource>
  query: string
}

export function emptyFilter(): LogFilter {
  return { levels: new Set(), sources: new Set(), query: '' }
}

export function filterLogs(logs: LogEntry[], f: LogFilter): LogEntry[] {
  const q = f.query.trim().toLowerCase()
  return logs.filter((l) => {
    if (f.levels.size && !f.levels.has(l.level)) return false
    if (f.sources.size && !f.sources.has(l.source)) return false
    if (q && !l.message.toLowerCase().includes(q) && !l.source.toLowerCase().includes(q)) return false
    return true
  })
}

export function capBuffer(logs: LogEntry[], max: number): LogEntry[] {
  return logs.length <= max ? logs : logs.slice(logs.length - max)
}

export function countByLevel(logs: LogEntry[], level: LogLevel): number {
  return logs.reduce((n, l) => (l.level === level ? n + 1 : n), 0)
}

// counts per 1-second slot over the last `windowSec` seconds; index 0 = oldest, last = newest
export function sparklineBuckets(logs: LogEntry[], now: number, windowSec: number): number[] {
  const out = new Array<number>(windowSec).fill(0)
  for (const l of logs) {
    const ageSec = Math.floor((now - l.ts) / 1000)
    if (ageSec >= 0 && ageSec < windowSec) out[windowSec - 1 - ageSec] += 1
  }
  return out
}
