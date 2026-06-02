// ============================================================================
// JARVIS SPATIAL DASHBOARD — V15 SHARED TYPES
// ============================================================================
import type { OperatorPose } from './sceneConstants'

export type SceneMode = 'morning' | 'afternoon' | 'evening' | 'night' | 'focus' | 'away'

// High-level Operator behaviour state (derived).
export type OperatorState = 'idle' | 'walking' | 'at-object'

// System "mood" — drives the Operator's glow colour + micro-behaviour.
export type SystemMood = 'idle' | 'processing' | 'busy' | 'warning' | 'success'

// Live service activity that drives object active-state animations.
export interface ServiceStates {
  spotify: boolean // music playing
  gmailUnread: number // >0 -> laptop blinks
  calendarAlert: boolean // upcoming event
  weatherAlert: boolean // storm etc.
  taskActive: boolean // a task is running -> rings/spins
  processing: boolean // AI busy -> core cube spins fast
}

export const DEFAULT_SERVICES: ServiceStates = {
  spotify: true,
  gmailUnread: 3,
  calendarAlert: true,
  weatherAlert: false,
  taskActive: false,
  processing: false,
}

// Where the Operator should go when an object is activated (clicked).
export interface ActiveTarget {
  id: string
  position: [number, number, number]
  rotationY: number
  pose: OperatorPose
}

// The object currently hovered (for tooltip + avatar head-tracking).
export interface HoveredObject {
  id: string
  label: string
  position: [number, number, number]
}

// One notification spark in flight (flies from `from` to the Operator, then pops).
export interface NotifSpark {
  id: number
  from: [number, number, number]
  color: string
}

// Callbacks threaded DOWN to furniture/objects (avoids R3F context-bridge risk).
export interface Interaction {
  activate: (target: ActiveTarget) => void
  hover: (obj: HoveredObject | null) => void
  notify: (from: [number, number, number], color?: string) => void
  activeId: string | null // which object is currently active (persistent state)
}

// Props passed to every room furniture module.
export interface RoomFurnitureProps {
  services: ServiceStates
  mood: SystemMood
  ix: Interaction
}
