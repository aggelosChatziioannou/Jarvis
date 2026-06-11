import { describe, it, expect } from 'vitest'
import { resolveAction, planFurnitureEffects, shouldFireArrival, FURNITURE_ACTIONS } from './furnitureActions'

describe('resolveAction', () => {
  it('maps the wired Living objects', () => {
    expect(resolveAction('living-vinyl')).toEqual({ kind: 'spotify', op: 'playpause' })
    expect(resolveAction('living-nowplaying')).toEqual({ kind: 'panel', panel: 'nowplaying' })
    expect(resolveAction('living-screen')).toEqual({ kind: 'panel', panel: 'nowplaying' })
    expect(resolveAction('living-headphones')).toEqual({ kind: 'focus' })
  })
  it('maps the other-room objects to real actions', () => {
    expect(resolveAction('office-laptop')).toEqual({ kind: 'panel', panel: 'gmail' })
    expect(resolveAction('office-tasks')).toEqual({ kind: 'panel', panel: 'reminders' })
    expect(resolveAction('office-pinboard')).toEqual({ kind: 'navigate', page: 'memory' })
    expect(resolveAction('control-devices')).toEqual({ kind: 'navigate', page: 'audio' })
    expect(resolveAction('control-server')).toEqual({ kind: 'panel', panel: 'system' })
    expect(resolveAction('control-core')).toEqual({ kind: 'panel', panel: 'model' })
    expect(resolveAction('wellness-water')).toEqual({ kind: 'reminder', label: 'Drink water 💧', afterMinutes: 60 })
    expect(resolveAction('wellness-sleep')).toEqual({ kind: 'lights' })
    expect(resolveAction('entrance-weather-station')).toEqual({ kind: 'panel', panel: 'weather' })
    expect(resolveAction('entrance-smart-lights')).toEqual({ kind: 'lights' })
    expect(resolveAction('run-script')).toEqual({ kind: 'testTone' })
  })
  it('returns undefined for non-wired objects', () => {
    expect(resolveAction('living-sofa')).toBeUndefined()
  })
  it('every registered action plans at least one effect', () => {
    for (const [id, action] of Object.entries(FURNITURE_ACTIONS)) {
      const effects = planFurnitureEffects(action, { spotifyPlaying: false, dndActive: false })
      expect(effects.length, `action for ${id} should plan effects`).toBeGreaterThan(0)
    }
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
  it('navigate => navigate effect', () => {
    expect(planFurnitureEffects({ kind: 'navigate', page: 'settings' }, { spotifyPlaying: false, dndActive: false }))
      .toEqual([{ type: 'navigate', page: 'settings' }])
  })
  it('lights => toggleLights', () => {
    expect(planFurnitureEffects({ kind: 'lights' }, { spotifyPlaying: false, dndActive: false }))
      .toEqual([{ type: 'toggleLights' }])
  })
  it('reminder => createReminder then opens the reminders panel (visible write)', () => {
    expect(planFurnitureEffects({ kind: 'reminder', label: 'Drink water 💧', afterMinutes: 60 }, { spotifyPlaying: false, dndActive: false }))
      .toEqual([
        { type: 'createReminder', label: 'Drink water 💧', afterMinutes: 60 },
        { type: 'openPanel', panel: 'reminders' },
      ])
  })
  it('testTone => testTone effect', () => {
    expect(planFurnitureEffects({ kind: 'testTone' }, { spotifyPlaying: false, dndActive: false }))
      .toEqual([{ type: 'testTone' }])
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

describe('friendlyActionFailure', () => {
  it('maps spotify no-active-device to an actionable hint', async () => {
    const { friendlyActionFailure } = await import('./furnitureActions')
    expect(friendlyActionFailure('spotify', 'no active device')).toMatch(/open Spotify/)
  })
  it('maps auth failures to settings hint', async () => {
    const { friendlyActionFailure } = await import('./furnitureActions')
    expect(friendlyActionFailure('spotify', 're-authorise Spotify')).toMatch(/Settings/)
  })
  it('maps network/daemon-down failures', async () => {
    const { friendlyActionFailure } = await import('./furnitureActions')
    expect(friendlyActionFailure('spotify', 'network')).toMatch(/is Jarvis running/)
    expect(friendlyActionFailure('reminder')).toMatch(/is Jarvis running/)
    expect(friendlyActionFailure('tone')).toMatch(/is Jarvis running/)
  })
})
