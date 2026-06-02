import { describe, it, expect } from 'vitest'
import { mapLevel, deriveSource, tsFromId, toLogEntry } from './logMap'
import type { LogPayload } from '@/lib/api'

describe('mapLevel (backend -> console level)', () => {
  it('maps each backend level', () => {
    expect(mapLevel('info')).toBe('info')
    expect(mapLevel('warning')).toBe('warn')
    expect(mapLevel('error')).toBe('error')
    expect(mapLevel('fast-path')).toBe('debug')
    expect(mapLevel('mcp')).toBe('info')
    expect(mapLevel('easter-egg')).toBe('success')
  })
})

describe('tsFromId (id is epoch seconds with micros)', () => {
  it('converts the epoch-seconds id to epoch ms', () => {
    expect(tsFromId('1717257314.123456', 0)).toBe(Math.round(1717257314.123456 * 1000))
  })
  it('falls back to now when the id is not numeric', () => {
    expect(tsFromId('not-a-number', 999)).toBe(999)
  })
})

describe('deriveSource (no source field on the wire; infer from message)', () => {
  it('routes wake/VAD lines to Wake', () => {
    expect(deriveSource('Wake word detected: "Jarvis"')).toBe('Wake')
    expect(deriveSource('VAD energy 0.71 > gate 0.55')).toBe('Wake')
  })
  it('routes TTS/utterance lines to Voice', () => {
    expect(deriveSource('TTS synthesis 412ms (cache miss)')).toBe('Voice')
    expect(deriveSource('Utterance delivered (1.8s)')).toBe('Voice')
  })
  it('routes memory/graph lines to Memory', () => {
    expect(deriveSource('Indexed 3 new episodic memories')).toBe('Memory')
    expect(deriveSource('Consolidated 12 facts into long-term store')).toBe('Memory')
  })
  it('routes mcp/service lines to Services', () => {
    expect(deriveSource('[mcp] spotify token refreshed')).toBe('Services')
    expect(deriveSource('Calendar synced — 4 events today')).toBe('Services')
  })
  it('routes mic/device lines to Audio', () => {
    expect(deriveSource('Input device: Default Microphone')).toBe('Audio')
    expect(deriveSource('RMS 0.013 · noise floor 0.004')).toBe('Audio')
  })
  it('defaults to System', () => {
    expect(deriveSource('Heartbeat OK — uptime 14h 23m')).toBe('System')
    expect(deriveSource('Configuration reloaded successfully')).toBe('System')
  })
})

describe('toLogEntry', () => {
  it('maps a backend payload to a console LogEntry, preserving the original in meta', () => {
    const p: LogPayload = {
      id: '1717257314.500000',
      timestamp: '14:35:14.50',
      level: 'warning',
      message: 'Gmail API rate limit at 80%',
    }
    const e = toLogEntry(p, 123)
    expect(e.id).toBe(p.id)
    expect(e.level).toBe('warn')
    expect(e.source).toBe('Services')
    expect(e.message).toBe(p.message)
    expect(e.ts).toBe(Math.round(1717257314.5 * 1000))
    expect(e.meta).toMatchObject({ backendLevel: 'warning', clock: '14:35:14.50' })
  })
})
