export type AudioMode = 'live' | 'demo'
export type PermissionState = 'idle' | 'granted' | 'denied' | 'unsupported'

export type AudioEventType =
  | 'mic-on' | 'mic-off' | 'permission-granted' | 'permission-denied'
  | 'device-changed' | 'voice-start' | 'voice-end' | 'peak' | 'test-tone' | 'error'

export type AudioEventLevel = 'info' | 'success' | 'warn' | 'error'

export interface AudioEvent {
  id: string
  ts: number
  type: AudioEventType
  level: AudioEventLevel
  message: string
  meta?: Record<string, unknown>
}

export interface AudioDevice {
  deviceId: string
  label: string
  kind: 'audioinput' | 'audiooutput'
}

export interface EngineParams {
  detection: number
  outputVolume: number
  noiseFloor: number
  smoothing: number
}

export interface LevelSnapshot { rms: number; db: number; peak: number }
export interface HealthSnapshot { quality: number; noise: number; clarity: number; responseMs: number }

export const EVENT_LEVEL: Record<AudioEventType, AudioEventLevel> = {
  'mic-on': 'success', 'mic-off': 'info', 'permission-granted': 'success', 'permission-denied': 'error',
  'device-changed': 'info', 'voice-start': 'info', 'voice-end': 'info', 'peak': 'warn', 'test-tone': 'info', 'error': 'error',
}

export const EVENT_COLORS: Record<AudioEventLevel, string> = {
  info: '#22d3ee', success: '#34d399', warn: '#fbbf24', error: '#ef4444',
}
