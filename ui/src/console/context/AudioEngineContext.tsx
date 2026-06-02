import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'
import { useAudioEngine, type AudioEngine } from '@/console/hooks/useAudioEngine'

const Ctx = createContext<AudioEngine | null>(null)

export function AudioEngineProvider({ children }: { children: ReactNode }) {
  const engine = useAudioEngine()
  return <Ctx.Provider value={engine}>{children}</Ctx.Provider>
}

export function useAudioEngineCtx(): AudioEngine {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAudioEngineCtx must be used within <AudioEngineProvider>')
  return v
}
