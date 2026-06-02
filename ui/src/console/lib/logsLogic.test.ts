import { describe, it, expect } from 'vitest'
import type { LogEntry, LogLevel, LogSource } from '@/console/types/logs'
import { filterLogs, capBuffer, sparklineBuckets, countByLevel, emptyFilter } from '@/console/lib/logsLogic'

const mk = (over: Partial<LogEntry>): LogEntry => ({
  id: 'x', ts: 1000, level: 'info', source: 'System', message: 'hello world', ...over,
})

describe('filterLogs', () => {
  const logs = [
    mk({ id: '1', level: 'info', source: 'System', message: 'boot ok' }),
    mk({ id: '2', level: 'error', source: 'Audio', message: 'buffer underrun' }),
    mk({ id: '3', level: 'warn', source: 'Memory', message: 'low confidence' }),
  ]
  it('returns all when filter is empty', () => {
    expect(filterLogs(logs, emptyFilter()).length).toBe(3)
  })
  it('filters by level set', () => {
    const f = { ...emptyFilter(), levels: new Set<LogLevel>(['error']) }
    expect(filterLogs(logs, f).map((l) => l.id)).toEqual(['2'])
  })
  it('filters by source set', () => {
    const f = { ...emptyFilter(), sources: new Set<LogSource>(['Memory']) }
    expect(filterLogs(logs, f).map((l) => l.id)).toEqual(['3'])
  })
  it('filters by query against message and source (case-insensitive)', () => {
    expect(filterLogs(logs, { ...emptyFilter(), query: 'UNDERRUN' }).map((l) => l.id)).toEqual(['2'])
    expect(filterLogs(logs, { ...emptyFilter(), query: 'memory' }).map((l) => l.id)).toEqual(['3'])
  })
})

describe('capBuffer', () => {
  it('keeps only the last N entries', () => {
    const logs = Array.from({ length: 10 }, (_, i) => mk({ id: String(i), ts: i }))
    const out = capBuffer(logs, 3)
    expect(out.map((l) => l.id)).toEqual(['7', '8', '9'])
  })
  it('returns the same array when under cap', () => {
    const logs = [mk({ id: 'a' })]
    expect(capBuffer(logs, 5).length).toBe(1)
  })
})

describe('countByLevel', () => {
  it('counts entries of a level', () => {
    const logs = [mk({ level: 'error' }), mk({ level: 'error' }), mk({ level: 'info' })]
    expect(countByLevel(logs, 'error')).toBe(2)
  })
})

describe('sparklineBuckets', () => {
  it('buckets entries into per-second slots over the window, newest last', () => {
    const now = 10_000
    const logs = [
      mk({ ts: 10_000 }), // age 0s -> last bucket
      mk({ ts: 9_000 }),  // age 1s
      mk({ ts: 9_000 }),  // age 1s
      mk({ ts: 1_000 }),  // age 9s -> outside a 5s window
    ]
    const out = sparklineBuckets(logs, now, 5)
    expect(out.length).toBe(5)
    expect(out[4]).toBe(1) // age 0
    expect(out[3]).toBe(2) // age 1
    expect(out.reduce((a, b) => a + b, 0)).toBe(3) // the 9s-old one is excluded
  })
})
