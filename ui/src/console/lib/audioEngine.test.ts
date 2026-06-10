import { describe, it, expect } from 'vitest'
import {
  rms, toDb, isVoice, smoothingToTC, gainFromVolume, capEvents,
  makeAudioEvent, demoTimeDomain, demoFrequency, deriveHealth,
} from '@/console/lib/audioEngine'

function silence(n = 16): Uint8Array { return new Uint8Array(n).fill(128) }
function loud(n = 16): Uint8Array { const a = new Uint8Array(n); for (let i = 0; i < n; i++) a[i] = i % 2 ? 255 : 0; return a }

describe('rms', () => {
  it('is ~0 for silence (centered at 128)', () => { expect(rms(silence())).toBeCloseTo(0, 5) })
  it('is ~1 for a full-scale square', () => { expect(rms(loud())).toBeCloseTo(1, 1) })
})

describe('toDb', () => {
  it('clamps silence to -60', () => { expect(toDb(0)).toBe(-60) })
  it('maps 1.0 to ~0 dB', () => { expect(toDb(1)).toBeCloseTo(0, 5) })
})

describe('isVoice', () => {
  it('false at/below the floor+threshold', () => { expect(isVoice(0.0, 20, 20)).toBe(false) })
  it('true for a loud signal', () => { expect(isVoice(0.9, 50, 20)).toBe(true) })
  it('higher detection threshold needs louder input', () => {
    expect(isVoice(0.2, 90, 20)).toBe(false)
    expect(isVoice(0.2, 0, 0)).toBe(true)
  })
})

describe('smoothingToTC', () => {
  it('maps 0→0 and 100→0.95, clamped', () => {
    expect(smoothingToTC(0)).toBe(0)
    expect(smoothingToTC(100)).toBeCloseTo(0.95, 5)
    expect(smoothingToTC(200)).toBe(0.95)
    expect(smoothingToTC(-50)).toBe(0)
  })
})

describe('gainFromVolume', () => {
  it('maps 0..100 → 0..1, clamped', () => {
    expect(gainFromVolume(0)).toBe(0)
    expect(gainFromVolume(50)).toBeCloseTo(0.5, 5)
    expect(gainFromVolume(150)).toBe(1)
  })
})

describe('capEvents', () => {
  it('keeps the last N', () => {
    const evs = Array.from({ length: 10 }, (_, i) => makeAudioEvent(i, 'mic-on', String(i)))
    expect(capEvents(evs, 3).map((e) => e.message)).toEqual(['7', '8', '9'])
  })
})

describe('makeAudioEvent', () => {
  it('assigns the mapped level and a unique id', () => {
    const a = makeAudioEvent(1, 'peak', 'p')
    const b = makeAudioEvent(1, 'peak', 'p')
    expect(a.level).toBe('warn')
    expect(a.id).not.toBe(b.id)
  })
})

describe('demo generators', () => {
  it('fill the array within byte range and are deterministic in t', () => {
    const a = new Uint8Array(32); const b = new Uint8Array(32)
    demoTimeDomain(a, 1.23); demoTimeDomain(b, 1.23)
    expect(Array.from(a)).toEqual(Array.from(b))
    expect(a.every((v) => v >= 0 && v <= 255)).toBe(true)
    const f = new Uint8Array(32); demoFrequency(f, 2.0)
    expect(f.every((v) => v >= 0 && v <= 255)).toBe(true)
  })
})

describe('deriveHealth', () => {
  it('returns 0..100 metrics and the passed responseMs', () => {
    const h = deriveHealth({ rms: 0.3, db: -10, peak: 0.5 }, 20, 22)
    expect(h.responseMs).toBe(22)
    for (const k of ['quality', 'noise', 'clarity'] as const) {
      expect(h[k]).toBeGreaterThanOrEqual(0)
      expect(h[k]).toBeLessThanOrEqual(100)
    }
  })
})

describe('renderRmsWave', () => {
  it('renders silence as a flat centre line', async () => {
    const { renderRmsWave } = await import('./audioEngine')
    const out = new Uint8Array(64)
    renderRmsWave(out, new Float32Array(16), 16)
    expect(out.every((v) => v === 128)).toBe(true)
  })
  it('renders loud history as deviation from centre', async () => {
    const { renderRmsWave } = await import('./audioEngine')
    const out = new Uint8Array(64)
    const hist = new Float32Array(16).fill(0.25)
    renderRmsWave(out, hist, 16)
    expect(Math.max(...out)).toBeGreaterThan(160)
    expect(Math.min(...out)).toBeLessThan(96)
  })
})

describe('renderBandSpectrum', () => {
  it('maps band energy onto the right region of bins', async () => {
    const { renderBandSpectrum } = await import('./audioEngine')
    const out = new Uint8Array(32)
    const spec = new Array(16).fill(0)
    spec[0] = 0.3 // low band only
    renderBandSpectrum(out, spec)
    expect(out[0]).toBeGreaterThan(100)
    expect(out[31]).toBe(0)
  })
  it('empty spectrum clears the bins', async () => {
    const { renderBandSpectrum } = await import('./audioEngine')
    const out = new Uint8Array(8).fill(200)
    renderBandSpectrum(out, [])
    expect(Math.max(...out)).toBe(0)
  })
})
