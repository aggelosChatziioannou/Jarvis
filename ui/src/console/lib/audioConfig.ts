// Maps the daemon config (GET/PATCH /api/config) to/from the Audio page's
// real-assistant controls. These are the ACTUAL listening knobs; changing them
// writes config and takes effect after a daemon restart (models stay resident).

import type { AudioDevice } from '@/lib/api'

export interface SensitivityField {
  key: string
  label: string
  hint: string
  min: number
  max: number
  step: number
  default: number
  unit?: string
}

// Real config fields (see src/jarvis/listening + config.py). Wispr is the live
// STT backend, so wake sensitivity is the openWakeWord threshold; VAD is Silero.
export const SENSITIVITY_FIELDS: SensitivityField[] = [
  {
    key: 'wispr_wake_threshold',
    label: 'Wake sensitivity',
    hint: 'openWakeWord score to trigger "Hey Jarvis". Lower = more sensitive (more false wakes).',
    min: 0,
    max: 1,
    step: 0.05,
    default: 0.1,
  },
  {
    key: 'vad_silero_threshold',
    label: 'Voice onset (VAD)',
    hint: 'Silero threshold to START capturing speech. Higher = stricter.',
    min: 0,
    max: 1,
    step: 0.05,
    default: 0.5,
  },
  {
    key: 'vad_silero_neg_threshold',
    label: 'Voice offset (VAD)',
    hint: 'Silero threshold to STOP capturing. Lower than onset so quiet tails are kept.',
    min: 0,
    max: 1,
    step: 0.05,
    default: 0.3,
  },
  {
    key: 'endpoint_silence_ms',
    label: 'End-of-speech silence',
    hint: 'Silence (ms) before an utterance is finalised.',
    min: 100,
    max: 2000,
    step: 50,
    default: 400,
    unit: 'ms',
  },
]

type Config = Record<string, unknown>

function num(value: unknown, fallback: number): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

export function readSensitivity(config: Config): Record<string, number> {
  const out: Record<string, number> = {}
  for (const f of SENSITIVITY_FIELDS) out[f.key] = num(config[f.key], f.default)
  return out
}

export function sensitivityPatch(values: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const f of SENSITIVITY_FIELDS) {
    if (f.key in values) out[f.key] = values[f.key]
  }
  return out
}

// --- Device selection ---
// Both selects are keyed by device NAME: the device list often reports empty
// endpoint ids (sounddevice fallback) and duplicate names across host APIs, so
// the friendly name is the reliable selector. We still persist the stable
// endpoint id when the list provides one (the daemon prefers it, then name).

export function selectedInput(config: Config): string {
  return String(config.audio_input_name ?? '')
}

export function selectedOutput(config: Config): string {
  return String(config.tts_output_device ?? '')
}

export function inputPatch(device: AudioDevice): Record<string, string> {
  // Empty id -> clear it so the daemon falls back to the chosen name.
  return { audio_input_endpoint_id: device.id ?? '', audio_input_name: device.name }
}

export function outputPatch(device: AudioDevice): Record<string, string> {
  return { tts_output_device: device.name }
}
