// Adapter: daemon log payloads (ui/src/lib/api LogPayload) -> console LogEntry.
//
// The daemon classifies a line into one of six levels and stamps an id of the
// form "<epoch_seconds>.<micros>" plus a clock-only timestamp. It does NOT tag a
// source, so we infer one from the message. Source inference is a best-effort
// keyword heuristic over internal English log text (not user-facing language).

import type { LogPayload } from '@/lib/api'
import type { LogEntry, LogLevel, LogSource } from '@/console/types/logs'

export function mapLevel(level: LogPayload['level']): LogLevel {
  switch (level) {
    case 'warning':
      return 'warn'
    case 'error':
      return 'error'
    case 'fast-path':
      return 'debug'
    case 'easter-egg':
      return 'success'
    case 'mcp':
    case 'info':
    default:
      return 'info'
  }
}

// Priority-ordered keyword groups; first hit wins so overlaps resolve sanely.
const SOURCE_RULES: Array<[LogSource, string[]]> = [
  ['Wake', ['wake', 'vad', 'openwakeword', 'hey jarvis', 'hotword']],
  ['Voice', ['tts', 'speak', 'utterance', 'synthes', 'voice']],
  ['Memory', ['memory', 'memories', 'graph', 'diary', 'episodic', 'consolidat', 'fact', 'node']],
  ['Services', ['mcp', 'spotify', 'gmail', 'calendar', 'weather', 'oauth', 'token', 'service']],
  ['Audio', ['audio', 'mic', 'device', 'rms', 'noise floor', 'capture', 'buffer', 'sample']],
]

export function deriveSource(message: string): LogSource {
  const m = message.toLowerCase()
  for (const [source, keywords] of SOURCE_RULES) {
    if (keywords.some((k) => m.includes(k))) return source
  }
  return 'System'
}

/** id is epoch seconds with micros ("1717257314.123456"); convert to epoch ms. */
export function tsFromId(id: string, nowMs: number): number {
  const secs = Number.parseFloat(id)
  return Number.isFinite(secs) ? Math.round(secs * 1000) : nowMs
}

export function toLogEntry(p: LogPayload, nowMs: number): LogEntry {
  return {
    id: p.id,
    ts: tsFromId(p.id, nowMs),
    level: mapLevel(p.level),
    source: deriveSource(p.message),
    message: p.message,
    meta: { backendLevel: p.level, clock: p.timestamp },
  }
}
