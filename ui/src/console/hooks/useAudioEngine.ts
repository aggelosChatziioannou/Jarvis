import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  AudioDevice, AudioEvent, AudioEventType, AudioMode, EngineParams, HealthSnapshot, LevelSnapshot, PermissionState,
} from '@/console/types/audio'
import {
  capEvents, deriveHealth, gainFromVolume, isVoice, makeAudioEvent, renderBandSpectrum, renderRmsWave, rms, smoothingToTC, toDb,
} from '@/console/lib/audioEngine'
import { openAudioStream } from '@/console/services/seam'
import type { AudioTelemetryPayload } from '@/console/services/seam'

const FFT = 2048
const FREQ_BINS = FFT / 2
const MAX_EVENTS = 200
const DEFAULT_PARAMS: EngineParams = { detection: 75, outputVolume: 85, noiseFloor: 20, smoothing: 60 }

type MediaWithSink = HTMLMediaElement & { setSinkId?: (id: string) => Promise<void> }

/** What the daemon's listener reports it is hearing right now. */
export interface DaemonAudio {
  connected: boolean
  state: string
  wake: number | null
  vad: number | null
  voiced: boolean
}

export interface AudioEngine {
  daemon: DaemonAudio
  timeRef: React.MutableRefObject<Uint8Array<ArrayBuffer>>
  freqRef: React.MutableRefObject<Uint8Array<ArrayBuffer>>
  levelRef: React.MutableRefObject<LevelSnapshot>
  vadRef: React.MutableRefObject<boolean>
  frameRef: React.MutableRefObject<number>
  mode: AudioMode
  permission: PermissionState
  running: boolean
  inputDevices: AudioDevice[]
  outputDevices: AudioDevice[]
  selectedInput: string
  selectedOutput: string
  params: EngineParams
  events: AudioEvent[]
  health: HealthSnapshot
  enable: () => Promise<void>
  disable: () => void
  setMode: (m: AudioMode) => void
  selectInput: (id: string) => Promise<void>
  selectOutput: (id: string) => void
  setParam: (k: keyof EngineParams, v: number) => void
  playTestTone: () => void
  testMic: () => void
  clearEvents: () => void
}

export function useAudioEngine(): AudioEngine {
  const timeRef = useRef<Uint8Array<ArrayBuffer>>(new Uint8Array(FFT) as Uint8Array<ArrayBuffer>)
  const freqRef = useRef<Uint8Array<ArrayBuffer>>(new Uint8Array(FREQ_BINS) as Uint8Array<ArrayBuffer>)
  const levelRef = useRef<LevelSnapshot>({ rms: 0, db: -60, peak: 0 })
  const vadRef = useRef(false)
  const frameRef = useRef(0)

  const [mode, setModeState] = useState<AudioMode>('demo')
  const [permission, setPermission] = useState<PermissionState>('idle')
  const [running, setRunning] = useState(false)
  const [inputDevices, setInputDevices] = useState<AudioDevice[]>([])
  const [outputDevices, setOutputDevices] = useState<AudioDevice[]>([])
  const [selectedInput, setSelectedInput] = useState('')
  const [selectedOutput, setSelectedOutput] = useState('')
  const [params, setParams] = useState<EngineParams>(DEFAULT_PARAMS)
  const [events, setEvents] = useState<AudioEvent[]>([])
  const [health, setHealth] = useState<HealthSnapshot>({ quality: 0, noise: 20, clarity: 0, responseMs: 0 })

  // Daemon telemetry: the listener's real signal, used whenever the browser
  // mic preview is off. RMS history feeds the scrolling waveform.
  const daemonFrameRef = useRef<AudioTelemetryPayload | null>(null)
  const daemonLastRef = useRef(0)
  const daemonHistRef = useRef<Float32Array>(new Float32Array(192))
  const daemonPosRef = useRef(0)
  const [daemon, setDaemon] = useState<DaemonAudio>({ connected: false, state: 'idle', wake: null, vad: null, voiced: false })

  const ctxRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const rafRef = useRef<number | null>(null)

  const modeRef = useRef(mode); modeRef.current = mode
  const paramsRef = useRef(params); paramsRef.current = params
  const runningRef = useRef(running); runningRef.current = running
  const selInRef = useRef(selectedInput); selInRef.current = selectedInput
  const selOutRef = useRef(selectedOutput); selOutRef.current = selectedOutput
  const prevVadRef = useRef(false)
  const lastPeakRef = useRef(0)
  const lastHealthRef = useRef(0)
  const enabledRef = useRef(false)     // synchronous source of truth for "live graph active"
  const switchingRef = useRef(false)   // guards concurrent input re-acquire

  const pushEvent = useCallback((type: AudioEventType, message: string, meta?: Record<string, unknown>) => {
    setEvents((prev) => capEvents([...prev, makeAudioEvent(Date.now(), type, message, meta)], MAX_EVENTS))
  }, [])

  const refreshDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return
    const list = await navigator.mediaDevices.enumerateDevices()
    const ins: AudioDevice[] = list.filter((d) => d.kind === 'audioinput')
      .map((d) => ({ deviceId: d.deviceId, label: d.label || 'Microphone', kind: 'audioinput' }))
    const outs: AudioDevice[] = list.filter((d) => d.kind === 'audiooutput')
      .map((d) => ({ deviceId: d.deviceId, label: d.label || 'Speaker', kind: 'audiooutput' }))
    setInputDevices(ins)
    setOutputDevices(outs)
    setSelectedInput((cur) => cur || ins[0]?.deviceId || '')
    setSelectedOutput((cur) => cur || outs[0]?.deviceId || '')
  }, [])

  const enable = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) { setPermission('unsupported'); return }
    if (enabledRef.current) return
    try {
      let ctx = ctxRef.current
      if (!ctx || ctx.state === 'closed') ctx = new AudioContext()
      ctxRef.current = ctx
      await ctx.resume()
      const id = selInRef.current
      const stream = await navigator.mediaDevices.getUserMedia({ audio: id ? { deviceId: { exact: id } } : true })
      streamRef.current = stream
      const source = ctx.createMediaStreamSource(stream)
      sourceRef.current = source
      const analyser = ctx.createAnalyser()
      analyser.fftSize = FFT
      analyser.smoothingTimeConstant = smoothingToTC(paramsRef.current.smoothing)
      source.connect(analyser)
      analyserRef.current = analyser
      enabledRef.current = true
      setPermission('granted'); setRunning(true); setModeState('live'); modeRef.current = 'live'
      pushEvent('permission-granted', 'Microphone access granted')
      pushEvent('mic-on', 'Microphone live')
      await refreshDevices()
    } catch {
      enabledRef.current = false
      setPermission('denied'); setModeState('demo'); modeRef.current = 'demo'; setRunning(false)
      pushEvent('permission-denied', 'Microphone access denied')
    }
  }, [pushEvent, refreshDevices])

  const disable = useCallback(() => {
    enabledRef.current = false
    streamRef.current?.getTracks().forEach((t) => t.stop())
    sourceRef.current?.disconnect()
    analyserRef.current?.disconnect()
    streamRef.current = null; sourceRef.current = null; analyserRef.current = null
    setRunning(false); setModeState('demo'); modeRef.current = 'demo'
    pushEvent('mic-off', 'Microphone stopped')
  }, [pushEvent])

  const setMode = useCallback((m: AudioMode) => { if (m === 'live') void enable(); else disable() }, [enable, disable])

  const selectInput = useCallback(async (id: string) => {
    setSelectedInput(id); selInRef.current = id
    pushEvent('device-changed', 'Input device changed')
    if (!enabledRef.current || switchingRef.current) return
    switchingRef.current = true
    try { disable(); await enable() } finally { switchingRef.current = false }
  }, [disable, enable, pushEvent])

  const selectOutput = useCallback((id: string) => {
    setSelectedOutput(id); selOutRef.current = id
    pushEvent('device-changed', 'Output device changed')
  }, [pushEvent])

  const setParam = useCallback((k: keyof EngineParams, v: number) => {
    setParams((p) => ({ ...p, [k]: v }))
    if (k === 'smoothing' && analyserRef.current) analyserRef.current.smoothingTimeConstant = smoothingToTC(v)
  }, [])

  const playTestTone = useCallback(() => {
    let ctx = ctxRef.current
    if (!ctx || ctx.state === 'closed') ctx = new AudioContext()
    ctxRef.current = ctx
    void ctx.resume()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = 440
    gain.gain.value = gainFromVolume(paramsRef.current.outputVolume)
    osc.connect(gain)
    const canSink = 'setSinkId' in HTMLMediaElement.prototype && typeof ctx.createMediaStreamDestination === 'function'
    if (canSink && selOutRef.current) {
      const dest = ctx.createMediaStreamDestination()
      gain.connect(dest)
      const el = document.createElement('audio') as MediaWithSink
      el.srcObject = dest.stream
      el.setSinkId?.(selOutRef.current).catch(() => {})
      void el.play().catch(() => {})
      window.setTimeout(() => { el.pause(); el.srcObject = null }, 800)
    } else {
      gain.connect(ctx.destination)
    }
    osc.start()
    osc.stop(ctx.currentTime + 0.6)
    pushEvent('test-tone', 'Test tone played', { hz: 440 })
  }, [pushEvent])

  const testMic = useCallback(() => {
    if (!enabledRef.current) void enable()
    pushEvent('mic-on', 'Mic test — speak now')
  }, [enable, pushEvent])

  const clearEvents = useCallback(() => setEvents([]), [])

  useEffect(() => {
    if (!navigator.mediaDevices?.getUserMedia) { setPermission('unsupported'); return }
    void refreshDevices()
  }, [refreshDevices])

  // Subscribe to the daemon's live audio telemetry (/ws/audio).
  useEffect(() => {
    const stop = openAudioStream((f) => {
      daemonFrameRef.current = f
      daemonLastRef.current = performance.now() / 1000
      const h = daemonHistRef.current
      h[daemonPosRef.current % h.length] = f.rms
      daemonPosRef.current += 1
    })
    const iv = window.setInterval(() => {
      const f = daemonFrameRef.current
      const fresh = f !== null && performance.now() / 1000 - daemonLastRef.current < 2
      setDaemon((prev) => {
        const next: DaemonAudio = fresh && f
          ? { connected: true, state: f.state, wake: f.wake, vad: f.vad, voiced: f.voiced }
          : { connected: false, state: 'idle', wake: null, vad: null, voiced: false }
        return prev.connected === next.connected && prev.state === next.state &&
          prev.wake === next.wake && prev.vad === next.vad && prev.voiced === next.voiced
          ? prev : next
      })
    }, 250)
    return () => { stop(); window.clearInterval(iv) }
  }, [])

  useEffect(() => {
    let alive = true
    const tick = () => {
      if (!alive) return
      if (document.hidden) { rafRef.current = requestAnimationFrame(tick); return }
      const t = performance.now() / 1000
      const time = timeRef.current
      const freq = freqRef.current
      const analyser = analyserRef.current
      const daemonFresh = daemonFrameRef.current !== null && t - daemonLastRef.current < 2
      if (modeRef.current === 'live' && analyser) {
        analyser.getByteTimeDomainData(time)
        analyser.getByteFrequencyData(freq)
      } else if (daemonFresh) {
        // Real signal from the daemon's listener — no browser mic needed.
        renderRmsWave(time, daemonHistRef.current, daemonPosRef.current)
        renderBandSpectrum(freq, daemonFrameRef.current!.spec)
      } else {
        // No source at all: honest flatline, not a fake demo wave.
        time.fill(128)
        freq.fill(0)
      }
      const r = rms(time)
      let peak = 0
      for (let i = 0; i < time.length; i++) { const v = Math.abs((time[i] - 128) / 128); if (v > peak) peak = v }
      levelRef.current = { rms: r, db: toDb(r), peak }
      const voice = modeRef.current !== 'live' && daemonFresh
        ? daemonFrameRef.current!.voiced
        : isVoice(r, paramsRef.current.detection, paramsRef.current.noiseFloor)
      vadRef.current = voice
      if (voice && !prevVadRef.current) pushEvent('voice-start', 'Voice detected')
      if (!voice && prevVadRef.current) pushEvent('voice-end', 'Voice ended')
      prevVadRef.current = voice
      if (peak > 0.98 && t - lastPeakRef.current > 1) { lastPeakRef.current = t; pushEvent('peak', 'Input peak / clipping', { db: Math.round(levelRef.current.db) }) }
      if (t - lastHealthRef.current > 0.2) {
        lastHealthRef.current = t
        const respMs = ctxRef.current ? Math.round((ctxRef.current.baseLatency || 0) * 1000) || 22 : 22
        setHealth(deriveHealth(levelRef.current, paramsRef.current.noiseFloor, respMs))
      }
      frameRef.current += 1
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => { alive = false; if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [pushEvent])

  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    if (ctxRef.current && ctxRef.current.state !== 'closed') void ctxRef.current.close()
  }, [])

  return useMemo<AudioEngine>(() => ({
    daemon,
    timeRef, freqRef, levelRef, vadRef, frameRef,
    mode, permission, running, inputDevices, outputDevices, selectedInput, selectedOutput, params, events, health,
    enable, disable, setMode, selectInput, selectOutput, setParam, playTestTone, testMic, clearEvents,
  }), [daemon, mode, permission, running, inputDevices, outputDevices, selectedInput, selectedOutput, params, events, health,
    enable, disable, setMode, selectInput, selectOutput, setParam, playTestTone, testMic, clearEvents])
}
