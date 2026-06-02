import { describe, it, expect } from 'vitest'
import {
  SENSITIVITY_FIELDS,
  readSensitivity,
  sensitivityPatch,
  selectedInput,
  selectedOutput,
  inputPatch,
  outputPatch,
} from './audioConfig'
import type { AudioDevice } from '@/lib/api'

describe('sensitivity config mapping', () => {
  it('applies real defaults when config is empty', () => {
    const v = readSensitivity({})
    expect(v.wispr_wake_threshold).toBe(0.1)
    expect(v.vad_silero_threshold).toBe(0.5)
    expect(v.vad_silero_neg_threshold).toBe(0.3)
    expect(v.endpoint_silence_ms).toBe(400)
  })

  it('reads stored values over defaults', () => {
    const v = readSensitivity({ wispr_wake_threshold: 0.45, endpoint_silence_ms: 600 })
    expect(v.wispr_wake_threshold).toBe(0.45)
    expect(v.endpoint_silence_ms).toBe(600)
    expect(v.vad_silero_threshold).toBe(0.5) // untouched -> default
  })

  it('builds a patch with exactly the sensitivity keys', () => {
    const patch = sensitivityPatch({
      wispr_wake_threshold: 0.4,
      vad_silero_threshold: 0.55,
      vad_silero_neg_threshold: 0.3,
      endpoint_silence_ms: 500,
    })
    expect(patch).toEqual({
      wispr_wake_threshold: 0.4,
      vad_silero_threshold: 0.55,
      vad_silero_neg_threshold: 0.3,
      endpoint_silence_ms: 500,
    })
  })

  it('every field has sane bounds containing its default', () => {
    for (const f of SENSITIVITY_FIELDS) {
      expect(f.min).toBeLessThan(f.max)
      expect(f.default).toBeGreaterThanOrEqual(f.min)
      expect(f.default).toBeLessThanOrEqual(f.max)
    }
  })
})

describe('device selection mapping', () => {
  const inDev: AudioDevice = { id: 'EP-IN-1', name: 'PD200X', is_default: false, available: true }
  const outDev: AudioDevice = { id: 'EP-OUT-1', name: 'Speakers (Realtek)', is_default: true, available: true }

  it('reads selected input (by name) / output from config', () => {
    expect(selectedInput({ audio_input_name: 'PD200X' })).toBe('PD200X')
    expect(selectedInput({})).toBe('')
    expect(selectedOutput({ tts_output_device: 'Speakers (Realtek)' })).toBe('Speakers (Realtek)')
    expect(selectedOutput({})).toBe('')
  })

  it('builds input/output patches from a chosen device', () => {
    expect(inputPatch(inDev)).toEqual({ audio_input_endpoint_id: 'EP-IN-1', audio_input_name: 'PD200X' })
    expect(outputPatch(outDev)).toEqual({ tts_output_device: 'Speakers (Realtek)' })
  })

  it('clears the endpoint id when the device list reports none', () => {
    const noId: AudioDevice = { id: '', name: 'PD200X', is_default: false, available: true }
    expect(inputPatch(noId)).toEqual({ audio_input_endpoint_id: '', audio_input_name: 'PD200X' })
  })
})
