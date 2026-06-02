import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api, openStateStream } from './seam'
import type { VoiceStatePayload } from './seam'
import type { AudioDevice } from '@/lib/api'
import {
  readSensitivity,
  sensitivityPatch,
  selectedInput as readSelectedInput,
  selectedOutput as readSelectedOutput,
  inputPatch,
  outputPatch,
} from '@/console/lib/audioConfig'

export interface AssistantAudio {
  connected: boolean
  state: VoiceStatePayload | null
  inputs: AudioDevice[]
  outputs: AudioDevice[]
  selectedInput: string
  selectedOutput: string
  sensitivity: Record<string, number>
  /** True once a config change was written; surfaces the "restart to apply" hint. */
  saved: boolean
  setInput: (d: AudioDevice) => Promise<void>
  setOutput: (d: AudioDevice) => Promise<void>
  saveSensitivity: (values: Record<string, number>) => Promise<void>
  testTone: () => void
  toggleMute: () => void
}

type Config = Record<string, unknown>

// The daemon lists the same device once per host API (MME/WASAPI/DirectSound),
// so collapse by friendly name to keep the selects clean.
function dedupeByName(devices: AudioDevice[]): AudioDevice[] {
  const seen = new Set<string>()
  const out: AudioDevice[] = []
  for (const d of devices) {
    if (seen.has(d.name)) continue
    seen.add(d.name)
    out.push(d)
  }
  return out
}

function useAssistantAudio(): AssistantAudio {
  const [connected, setConnected] = useState(false)
  const [state, setState] = useState<VoiceStatePayload | null>(null)
  const [config, setConfig] = useState<Config>({})
  const [inputs, setInputs] = useState<AudioDevice[]>([])
  const [outputs, setOutputs] = useState<AudioDevice[]>([])
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .getConfig()
      .then((c) => {
        if (alive) {
          setConfig(c)
          setConnected(true)
        }
      })
      .catch(() => {})
    api
      .audioDevices()
      .then((d) => {
        if (!alive) return
        setInputs(dedupeByName(d.inputs))
        setOutputs(dedupeByName(d.outputs))
      })
      .catch(() => {})
    const stop = openStateStream((s) => {
      if (!alive) return
      setState(s)
      setConnected(true)
    })
    return () => {
      alive = false
      stop()
    }
  }, [])

  const patch = useCallback(async (updates: Record<string, unknown>) => {
    await api.patchConfig(updates)
    setConfig((prev) => ({ ...prev, ...updates }))
    setSaved(true)
  }, [])

  const setInput = useCallback((d: AudioDevice) => patch(inputPatch(d)), [patch])
  const setOutput = useCallback((d: AudioDevice) => patch(outputPatch(d)), [patch])
  const saveSensitivity = useCallback(
    (values: Record<string, number>) => patch(sensitivityPatch(values)),
    [patch],
  )
  const testTone = useCallback(() => {
    void api.testTone()
  }, [])
  const toggleMute = useCallback(() => {
    void (state?.isMuted ? api.unmute() : api.mute())
  }, [state])

  return {
    connected,
    state,
    inputs,
    outputs,
    selectedInput: readSelectedInput(config),
    selectedOutput: readSelectedOutput(config),
    sensitivity: readSensitivity(config),
    saved,
    setInput,
    setOutput,
    saveSensitivity,
    testTone,
    toggleMute,
  }
}

const Ctx = createContext<AssistantAudio | null>(null)

export function AssistantAudioProvider({ children }: { children: ReactNode }) {
  return <Ctx.Provider value={useAssistantAudio()}>{children}</Ctx.Provider>
}

export function useAssistantAudioCtx(): AssistantAudio {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAssistantAudioCtx must be used within <AssistantAudioProvider>')
  return v
}
