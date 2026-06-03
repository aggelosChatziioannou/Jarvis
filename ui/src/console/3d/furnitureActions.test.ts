import { describe, it, expect } from 'vitest'
import { resolveAction, planFurnitureEffects, shouldFireArrival } from './furnitureActions'

describe('resolveAction', () => {
  it('maps the wired Living objects', () => {
    expect(resolveAction('living-vinyl')).toEqual({ kind: 'spotify', op: 'playpause' })
    expect(resolveAction('living-nowplaying')).toEqual({ kind: 'panel', panel: 'nowplaying' })
    expect(resolveAction('living-screen')).toEqual({ kind: 'panel', panel: 'nowplaying' })
    expect(resolveAction('living-headphones')).toEqual({ kind: 'focus' })
  })
  it('returns undefined for non-wired objects', () => {
    expect(resolveAction('living-sofa')).toBeUndefined()
    expect(resolveAction('office-laptop')).toBeUndefined()
  })
})

describe('planFurnitureEffects', () => {
  it('spotify playpause => optimistic toggle + control', () => {
    expect(planFurnitureEffects({ kind: 'spotify', op: 'playpause' }, { spotifyPlaying: true, dndActive: false }))
      .toEqual([{ type: 'spotify', op: 'playpause', optimisticToggle: true }])
  })
  it('panel => openPanel', () => {
    expect(planFurnitureEffects({ kind: 'panel', panel: 'nowplaying' }, { spotifyPlaying: false, dndActive: false }))
      .toEqual([{ type: 'openPanel', panel: 'nowplaying' }])
  })
  it('focus while playing+off => toggleDnd then pauseMusic', () => {
    expect(planFurnitureEffects({ kind: 'focus' }, { spotifyPlaying: true, dndActive: false }))
      .toEqual([{ type: 'toggleDnd' }, { type: 'pauseMusic' }])
  })
  it('focus while not playing => only toggleDnd', () => {
    expect(planFurnitureEffects({ kind: 'focus' }, { spotifyPlaying: false, dndActive: false }))
      .toEqual([{ type: 'toggleDnd' }])
  })
  it('focus when already active (turning off) => only toggleDnd, no pause', () => {
    expect(planFurnitureEffects({ kind: 'focus' }, { spotifyPlaying: true, dndActive: true }))
      .toEqual([{ type: 'toggleDnd' }])
  })
})

describe('shouldFireArrival', () => {
  it('fires once per nonce', () => {
    expect(shouldFireArrival(null, true, 1)).toBe(true)
    expect(shouldFireArrival(1, true, 1)).toBe(false)
    expect(shouldFireArrival(1, true, 2)).toBe(true)
  })
  it('does not fire before arrival', () => {
    expect(shouldFireArrival(null, false, 1)).toBe(false)
  })
})
