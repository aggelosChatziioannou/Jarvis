import { createContext, useContext, useState, useCallback, useRef, useMemo } from 'react'
import type { ReactNode } from 'react'
import type {
  SceneMode,
  SystemMood,
  ServiceStates,
  ActiveTarget,
  HoveredObject,
  NotifSpark,
  OperatorState,
} from './dollhouseTypes'
import { DEFAULT_SERVICES } from './dollhouseTypes'

export type { SceneMode } from './dollhouseTypes'

interface SceneContextType {
  sceneMode: SceneMode
  setSceneMode: (m: SceneMode) => void
  nightMode: boolean
  toggleNightMode: () => void

  mood: SystemMood
  setMood: (m: SystemMood) => void
  services: ServiceStates
  setServices: (s: ServiceStates) => void
  toggleService: (k: keyof ServiceStates) => void

  // Interaction state
  activeTarget: ActiveTarget | null
  setActiveTarget: (t: ActiveTarget | null) => void
  hovered: HoveredObject | null
  setHovered: (h: HoveredObject | null) => void
  operatorState: OperatorState

  notifications: NotifSpark[]
  pushNotification: (from: [number, number, number], color?: string) => void
  removeNotification: (id: number) => void

  focusMode: boolean
  toggleFocusMode: () => void
}

const noop = () => {}
const SceneContext = createContext<SceneContextType>({
  sceneMode: 'afternoon', setSceneMode: noop,
  nightMode: false, toggleNightMode: noop,
  mood: 'idle', setMood: noop,
  services: DEFAULT_SERVICES, setServices: noop, toggleService: noop,
  activeTarget: null, setActiveTarget: noop,
  hovered: null, setHovered: noop,
  operatorState: 'idle',
  notifications: [], pushNotification: noop, removeNotification: noop,
  focusMode: false, toggleFocusMode: noop,
})

export function useSceneContext() {
  return useContext(SceneContext)
}

export function SceneProvider({ children }: { children: ReactNode }) {
  const [sceneMode, setSceneMode] = useState<SceneMode>('afternoon')
  const [nightMode, setNightMode] = useState(false)
  const [mood, setMood] = useState<SystemMood>('idle')
  const [services, setServices] = useState<ServiceStates>(DEFAULT_SERVICES)
  const [activeTarget, setActiveTarget] = useState<ActiveTarget | null>(null)
  const [hovered, setHovered] = useState<HoveredObject | null>(null)
  const [notifications, setNotifications] = useState<NotifSpark[]>([])
  const notifId = useRef(1)
  const [focusMode, setFocusMode] = useState(false)
  const toggleFocusMode = useCallback(() => setFocusMode((p) => !p), [])

  const toggleNightMode = useCallback(() => {
    setNightMode((prev) => {
      const next = !prev
      setSceneMode(next ? 'night' : 'afternoon')
      return next
    })
  }, [])

  const toggleService = useCallback((k: keyof ServiceStates) => {
    setServices((prev) => {
      const cur = prev[k]
      if (typeof cur === 'boolean') return { ...prev, [k]: !cur }
      return { ...prev, [k]: cur > 0 ? 0 : 3 }
    })
  }, [])

  const pushNotification = useCallback((from: [number, number, number], color = '#22d3ee') => {
    const id = notifId.current++
    setNotifications((prev) => [...prev.slice(-6), { id, from, color }])
  }, [])

  const removeNotification = useCallback((id: number) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id))
  }, [])

  const operatorState: OperatorState = activeTarget ? 'at-object' : 'idle'

  const value = useMemo(
    () => ({
      sceneMode, setSceneMode, nightMode, toggleNightMode,
      mood, setMood, services, setServices, toggleService,
      activeTarget, setActiveTarget, hovered, setHovered, operatorState,
      notifications, pushNotification, removeNotification,
      focusMode, toggleFocusMode,
    }),
    [sceneMode, nightMode, toggleNightMode, mood, services, toggleService,
      activeTarget, hovered, operatorState, notifications, pushNotification, removeNotification,
      focusMode, toggleFocusMode],
  )

  return <SceneContext.Provider value={value}>{children}</SceneContext.Provider>
}
