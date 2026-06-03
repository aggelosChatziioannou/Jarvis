// Registry + pure decision logic for "embodied" furniture actions.
// Pure (no React, no 3D) so it is unit-testable. See the dispatcher hook
// (useFurnitureActions) for the side-effecting execution of the effects.

export type FurnitureAction =
  | { kind: 'spotify'; op: 'playpause' | 'next' | 'prev' }
  | { kind: 'panel'; panel: 'nowplaying' }
  | { kind: 'focus' }
  | { kind: 'voice'; utterance: string } // reserved for future objects; unused this slice

// Map of object id -> action. Unknown ids resolve to undefined and stay
// embodied-walk-only (the dispatcher no-ops).
export const FURNITURE_ACTIONS: Record<string, FurnitureAction> = {
  'living-vinyl': { kind: 'spotify', op: 'playpause' },
  'living-nowplaying': { kind: 'panel', panel: 'nowplaying' },
  'living-screen': { kind: 'panel', panel: 'nowplaying' },
  'living-headphones': { kind: 'focus' },
}

export function resolveAction(id: string): FurnitureAction | undefined {
  return FURNITURE_ACTIONS[id]
}

export type FurnitureEffect =
  | { type: 'spotify'; op: 'playpause' | 'next' | 'prev'; optimisticToggle: boolean }
  | { type: 'openPanel'; panel: 'nowplaying' }
  | { type: 'toggleDnd' }
  | { type: 'pauseMusic' }

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
    case 'focus': {
      const enabling = !ctx.dndActive
      const effects: FurnitureEffect[] = [{ type: 'toggleDnd' }]
      if (enabling && ctx.spotifyPlaying) effects.push({ type: 'pauseMusic' })
      return effects
    }
    case 'voice':
      return []
  }
}

// True when the Operator has just arrived for an activation we have not fired yet.
export function shouldFireArrival(firedNonce: number | null, arrived: boolean, nonce: number): boolean {
  return arrived && firedNonce !== nonce
}
