import type { AudioEvent, AudioEventType, HealthSnapshot, LevelSnapshot } from '@/console/types/audio'
import { EVENT_LEVEL } from '@/console/types/audio'

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export function rms(time: Uint8Array): number {
  let sum = 0
  for (let i = 0; i < time.length; i++) {
    const v = (time[i] - 128) / 128
    sum += v * v
  }
  return Math.sqrt(sum / time.length)
}

export function toDb(r: number): number {
  if (r <= 0) return -60
  return clamp(20 * Math.log10(r), -60, 0)
}

export function isVoice(r: number, thresholdPct: number, noiseFloorPct: number): boolean {
  const floor = (noiseFloorPct / 100) * 0.3
  const threshold = floor + (thresholdPct / 100) * 0.25
  return r > threshold
}

export function smoothingToTC(pct: number): number {
  return clamp(pct / 100, 0, 1) * 0.95
}

export function gainFromVolume(pct: number): number {
  return clamp(pct / 100, 0, 1)
}

let seq = 0
export function makeAudioEvent(ts: number, type: AudioEventType, message: string, meta?: Record<string, unknown>): AudioEvent {
  seq += 1
  return { id: `aevt-${ts}-${seq}`, ts, type, level: EVENT_LEVEL[type], message, meta }
}

export function capEvents(events: AudioEvent[], max: number): AudioEvent[] {
  return events.length <= max ? events : events.slice(events.length - max)
}

export function demoTimeDomain(out: Uint8Array, t: number): void {
  const n = out.length
  for (let i = 0; i < n; i++) {
    const x = i / n
    const wave =
      Math.sin(x * Math.PI * 8 + t * 2) * 0.4 +
      Math.sin(x * Math.PI * 20 + t * 3) * 0.15 +
      Math.sin(t * 1.5) * 0.2 * Math.sin(x * Math.PI * 2)
    out[i] = clamp(Math.round(128 + wave * 110), 0, 255)
  }
}

export function demoFrequency(out: Uint8Array, t: number): void {
  const n = out.length
  for (let i = 0; i < n; i++) {
    const x = i / n
    const env = Math.pow(1 - x, 1.8)
    const pulse = 0.5 + 0.5 * Math.sin(t * 2 + x * 6)
    out[i] = clamp(Math.round(env * pulse * 230), 0, 255)
  }
}

export function deriveHealth(level: LevelSnapshot, noiseFloorPct: number, responseMs: number): HealthSnapshot {
  const noise = Math.round(clamp(noiseFloorPct, 0, 100))
  const clarity = Math.round(clamp(level.peak * 140 - noise * 0.5, 0, 100))
  const quality = Math.round(clamp(100 - (level.peak > 0.98 ? 40 : 0) - noise * 0.4, 0, 100))
  return { quality, noise, clarity, responseMs: Math.round(responseMs) }
}
