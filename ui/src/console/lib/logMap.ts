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
  ['Wake', ['wake', 'vad', 'openwakeword', 'hey jarvis', 'hotword', 'wispr bridge', 'wispr flow', 'dictation', 'hot window', 'hot-window']],
  ['Voice', ['tts', 'speak', 'utterance', 'synthes', 'voice', 'whisper', 'transcri', 'heard', 'piper', 'barg', 'stt']],
  ['Memory', ['memory', 'memories', 'graph', 'diary', 'episodic', 'consolidat', 'fact', 'node', 'remember', 'forget']],
  // Brain before Services: a tool call like "Agent → getWeather" is LLM
  // activity even though the tool name mentions a service.
  ['Brain', ['intent', 'llm', 'ollama', 'reply', 'planner', 'router', 'tool', 'agent →', 'thinking', 'generating', 'working on it', '🤖', '🧠', '✨', '💬', '🛠']],
  ['Services', ['mcp', 'spotify', 'gmail', 'calendar', 'weather', 'oauth', 'token', 'service', 'reminder']],
  ['Audio', ['audio', 'mic', 'device', 'rms', 'noise floor', 'capture', 'buffer', 'sample']],
]

export function deriveSource(message: string): LogSource {
  const m = message.toLowerCase()
  for (const [source, keywords] of SOURCE_RULES) {
    if (keywords.some((k) => m.includes(k))) return source
  }
  return 'System'
}

// Plain-language descriptions for the high-signal pipeline events, anchored
// on the daemon's stable emoji/text markers (not on user speech content).
// Shown as the "live activity" line so a non-developer can follow along.
const ACTIVITY_RULES: Array<[RegExp, string]> = [
  [/⏹/u, 'Stopped on your request'],
  [/📝 heard|starting dictation/iu, 'Heard you — working out if that was for Jarvis'],
  [/intent.*: directed|accepting hot window/i, 'Decided you were talking to Jarvis'],
  [/intent.*not directed|no wake word found/i, 'Decided that was not addressed to Jarvis'],
  [/✨ working on it|💬 generating/iu, 'Thinking — generating a reply'],
  [/🛠/u, 'Using a tool to look something up or act'],
  [/🤖 jarvis/iu, 'Replied — speaking the answer'],
  [/knowledge graph: learned/i, 'Learned new facts into long-term memory'],
  [/knowledge graph: nothing new/i, 'Checked the conversation — nothing new to remember'],
  [/updating your diary|writing diary entry/i, 'Writing the conversation diary'],
  [/wake word|hey jarvis['"]?\s*detected/i, 'Wake word heard'],
  [/listening via wispr|🎙|listening! try/iu, 'Idle — listening for "Hey Jarvis"'],
  [/stt backend change|switching stt backend/i, 'Switching speech-to-text engine'],
  [/reminder.*fired|🔔/iu, 'Delivering a reminder'],
]

/** Plain-language summary of what Jarvis is doing, or null for routine lines. */
export function describeActivity(message: string): string | null {
  for (const [re, text] of ACTIVITY_RULES) {
    if (re.test(message)) return text
  }
  return null
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
