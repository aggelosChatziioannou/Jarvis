import { describe, it, expect } from 'vitest'
import { statusDisplay } from './statusMap'

describe('statusDisplay', () => {
  it('shows Offline when not connected, regardless of state', () => {
    expect(statusDisplay({ state: 'speaking', isMuted: false }, false).label).toBe('Offline')
  })

  it('maps live voice states to labels', () => {
    expect(statusDisplay({ state: 'idle', isMuted: false }, true).label).toBe('Idle')
    expect(statusDisplay({ state: 'listening', isMuted: false }, true).label).toBe('Listening')
    expect(statusDisplay({ state: 'thinking', isMuted: false }, true).label).toBe('Thinking')
    expect(statusDisplay({ state: 'speaking', isMuted: false }, true).label).toBe('Speaking')
  })

  it('collapses synthesizing to Thinking (daemon never emits it, but be safe)', () => {
    expect(statusDisplay({ state: 'synthesizing', isMuted: false }, true).label).toBe('Thinking')
  })

  it('muted overrides the activity label', () => {
    expect(statusDisplay({ state: 'listening', isMuted: true }, true).label).toBe('Muted')
  })

  it('defaults to Idle when connected but no state yet', () => {
    expect(statusDisplay(null, true).label).toBe('Idle')
  })
})
