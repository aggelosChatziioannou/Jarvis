// Registry + pure decision logic for "embodied" furniture actions.
// Pure (no React, no 3D) so it is unit-testable. See the dispatcher hook
// (useFurnitureActions) for the side-effecting execution of the effects.

export type PanelId =
  | 'nowplaying'
  | 'system'
  | 'weather'
  | 'gmail'
  | 'calendar'
  | 'reminders'
  | 'model'

export type ConsolePage = 'memory' | 'audio' | 'logs' | 'settings'

export type FurnitureAction =
  | { kind: 'spotify'; op: 'playpause' | 'next' | 'prev' }
  | { kind: 'panel'; panel: PanelId }
  | { kind: 'navigate'; page: ConsolePage }
  | { kind: 'focus' }
  | { kind: 'lights' }
  | { kind: 'reminder'; label: string; afterMinutes: number }
  | { kind: 'testTone' }
  | { kind: 'voice'; utterance: string } // reserved for future objects; unused this slice

// Map of object id -> action. Unknown ids resolve to undefined and stay
// embodied-walk-only (the dispatcher no-ops).
export const FURNITURE_ACTIONS: Record<string, FurnitureAction> = {
  // Living Room — entertainment
  'living-vinyl': { kind: 'spotify', op: 'playpause' },
  'living-nowplaying': { kind: 'panel', panel: 'nowplaying' },
  'living-screen': { kind: 'panel', panel: 'nowplaying' },
  'living-headphones': { kind: 'focus' },
  // 'living-sofa' stays embodied-walk-only (relax pose, no side effect)

  // Office — productivity
  'office-laptop': { kind: 'panel', panel: 'gmail' },
  'office-monitor': { kind: 'panel', panel: 'system' },
  'office-calendar': { kind: 'panel', panel: 'calendar' },
  'office-pinboard': { kind: 'navigate', page: 'memory' },
  'office-tasks': { kind: 'panel', panel: 'reminders' },
  'office-cabinet': { kind: 'navigate', page: 'memory' },

  // Control Room — system
  'control-security': { kind: 'navigate', page: 'settings' },
  'control-settings': { kind: 'navigate', page: 'settings' },
  'control-devices': { kind: 'navigate', page: 'audio' },
  'control-server': { kind: 'panel', panel: 'system' },
  'control-core': { kind: 'panel', panel: 'model' },
  'control-energy': { kind: 'panel', panel: 'system' },

  // Wellness
  'wellness-fitness': { kind: 'panel', panel: 'reminders' },
  'wellness-water': { kind: 'reminder', label: 'Drink water 💧', afterMinutes: 60 },
  'wellness-meditate': { kind: 'focus' },
  'wellness-sleep': { kind: 'lights' },

  // Studio / Dev Lab
  'code-editor': { kind: 'navigate', page: 'logs' },
  'run-script': { kind: 'testTone' },
  'system-monitor': { kind: 'panel', panel: 'system' },
  'automation': { kind: 'navigate', page: 'settings' },

  // Entrance / Threshold
  'entrance-front-door': { kind: 'panel', panel: 'weather' },
  'entrance-env-monitor': { kind: 'panel', panel: 'weather' },
  'entrance-weather-station': { kind: 'panel', panel: 'weather' },
  'entrance-smart-lights': { kind: 'lights' },
  'entrance-access-scanner': { kind: 'navigate', page: 'settings' },
}

export function resolveAction(id: string): FurnitureAction | undefined {
  return FURNITURE_ACTIONS[id]
}

export type FurnitureEffect =
  | { type: 'spotify'; op: 'playpause' | 'next' | 'prev'; optimisticToggle: boolean }
  | { type: 'openPanel'; panel: PanelId }
  | { type: 'navigate'; page: ConsolePage }
  | { type: 'toggleDnd' }
  | { type: 'pauseMusic' }
  | { type: 'toggleLights' }
  | { type: 'createReminder'; label: string; afterMinutes: number }
  | { type: 'testTone' }

export interface DispatchCtx {
  spotifyPlaying: boolean
  dndActive: boolean
}

export function planFurnitureEffects(action: FurnitureAction, ctx: DispatchCtx): FurnitureEffect[] {
  switch (action.kind) {
    case 'spotify':
      return [{ type: 'spotify', op: action.op, optimisticToggle: action.op === 'playpause' }]
    case 'panel':
      return [{ type: 'openPanel', panel: action.panel }]
    case 'navigate':
      return [{ type: 'navigate', page: action.page }]
    case 'focus': {
      const enabling = !ctx.dndActive
      const effects: FurnitureEffect[] = [{ type: 'toggleDnd' }]
      if (enabling && ctx.spotifyPlaying) effects.push({ type: 'pauseMusic' })
      return effects
    }
    case 'lights':
      return [{ type: 'toggleLights' }]
    case 'reminder':
      // Creating the reminder also opens the reminders panel so the action
      // is visible (and deletable) immediately — never a silent write.
      return [
        { type: 'createReminder', label: action.label, afterMinutes: action.afterMinutes },
        { type: 'openPanel', panel: 'reminders' },
      ]
    case 'testTone':
      return [{ type: 'testTone' }]
    case 'voice':
      return []
  }
}

// True when the Operator has just arrived for an activation we have not fired yet.
export function shouldFireArrival(firedNonce: number | null, arrived: boolean, nonce: number): boolean {
  return arrived && firedNonce !== nonce
}

// Map backend failure reasons to a short, actionable notice. Furniture
// actions must never fail silently — the user just watched the Operator walk
// over and press the thing.
export function friendlyActionFailure(kind: 'spotify' | 'reminder' | 'tone', reason?: string): string {
  if (kind === 'spotify') {
    const r = (reason || '').toLowerCase()
    if (r.includes('no active device')) return 'Spotify: no active device — open Spotify and press play once, then retry'
    if (r.includes('authoris') || r.includes('authoriz')) return 'Spotify is not connected — re-authorise it in Settings'
    if (r.includes('network') || r.includes('http')) return 'Spotify control failed — is Jarvis running?'
    return `Spotify control failed${reason ? ` (${reason})` : ''}`
  }
  if (kind === 'reminder') return 'Reminder could not be saved — is Jarvis running?'
  return 'Test tone failed — is Jarvis running?'
}
