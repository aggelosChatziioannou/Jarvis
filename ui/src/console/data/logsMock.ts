import type { LogEntry, LogLevel, LogSource } from '@/console/types/logs'

interface Template { source: LogSource; level: LogLevel; message: string }

export const MESSAGE_BANK: Template[] = [
  { source: 'System', level: 'info', message: 'Heartbeat OK — uptime 14h 23m' },
  { source: 'System', level: 'success', message: 'Configuration reloaded successfully' },
  { source: 'System', level: 'warn', message: 'CPU temperature 71°C (threshold 75°C)' },
  { source: 'System', level: 'debug', message: 'GC pause 4.2ms (gen-2)' },
  { source: 'Memory', level: 'info', message: 'Indexed 3 new episodic memories' },
  { source: 'Memory', level: 'success', message: 'Consolidated 12 facts into long-term store' },
  { source: 'Memory', level: 'warn', message: 'Node confidence below threshold (0.42)' },
  { source: 'Audio', level: 'info', message: 'Input device: Default Microphone' },
  { source: 'Audio', level: 'error', message: 'Buffer underrun on capture stream' },
  { source: 'Audio', level: 'debug', message: 'RMS 0.013 · noise floor 0.004' },
  { source: 'Services', level: 'success', message: 'Spotify token refreshed' },
  { source: 'Services', level: 'warn', message: 'Gmail API rate limit at 80%' },
  { source: 'Services', level: 'info', message: 'Calendar synced — 4 events today' },
  { source: 'Wake', level: 'success', message: 'Wake word detected: "Jarvis"' },
  { source: 'Wake', level: 'debug', message: 'VAD energy 0.71 > gate 0.55' },
  { source: 'Voice', level: 'info', message: 'TTS synthesis 412ms (cache miss)' },
  { source: 'Voice', level: 'success', message: 'Utterance delivered (1.8s)' },
  { source: 'Voice', level: 'debug', message: 'Selected voice model: aria-v2' },
]

let seq = 0
function nextId(ts: number): string {
  seq += 1
  return `log-${ts}-${seq}`
}

export function pickTemplate(): Template {
  return MESSAGE_BANK[Math.floor(Math.random() * MESSAGE_BANK.length)]
}

export function makeLogEntry(ts: number, t: Template = pickTemplate()): LogEntry {
  return { id: nextId(ts), ts, level: t.level, source: t.source, message: t.message, meta: { seq } }
}

// Seed `count` entries spread over the recent past (older first, newest last).
export function seedLogs(count: number, now: number): LogEntry[] {
  const out: LogEntry[] = []
  for (let i = count - 1; i >= 0; i -= 1) {
    const ts = now - i * 1500 - Math.floor(Math.random() * 800)
    out.push(makeLogEntry(ts))
  }
  return out
}
