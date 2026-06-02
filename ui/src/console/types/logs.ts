export type LogLevel = 'info' | 'success' | 'warn' | 'error' | 'debug'
export type LogSource = 'System' | 'Memory' | 'Audio' | 'Services' | 'Wake' | 'Voice'

export interface LogEntry {
  id: string
  ts: number
  level: LogLevel
  source: LogSource
  message: string
  meta?: Record<string, unknown>
}

export const LOG_LEVELS: LogLevel[] = ['info', 'success', 'warn', 'error', 'debug']
export const LOG_SOURCES: LogSource[] = ['System', 'Memory', 'Audio', 'Services', 'Wake', 'Voice']

export const LEVEL_COLORS: Record<LogLevel, string> = {
  info: '#22d3ee', success: '#34d399', warn: '#fbbf24', error: '#ef4444', debug: '#475569',
}
export const SOURCE_COLORS: Record<LogSource, string> = {
  System: '#94a3b8', Memory: '#a78bfa', Audio: '#22d3ee', Services: '#38bdf8', Wake: '#fbbf24', Voice: '#34d399',
}
