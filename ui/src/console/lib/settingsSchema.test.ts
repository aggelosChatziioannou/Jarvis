import { describe, it, expect } from 'vitest'
import { settingsDiff, coerce, SETTINGS_FIELDS } from './settingsSchema'

describe('settingsDiff', () => {
  it('returns only the changed keys', () => {
    expect(settingsDiff({ a: 1, b: 'x' }, { a: 1, b: 'y' })).toEqual({ b: 'y' })
  })
  it('is empty when nothing changed (untouched masked secrets stay put)', () => {
    expect(settingsDiff({ key: '••••••', n: 5 }, { key: '••••••', n: 5 })).toEqual({})
  })
  it('includes a newly typed secret', () => {
    expect(settingsDiff({ key: '••••••' }, { key: 'real-new-key' })).toEqual({ key: 'real-new-key' })
  })
})

describe('coerce', () => {
  it('parses numbers from input strings', () => {
    expect(coerce('0.45', 'number')).toBe(0.45)
    expect(coerce('3', 'number')).toBe(3)
  })
  it('passes text/select/password through as strings', () => {
    expect(coerce('wispr', 'select')).toBe('wispr')
    expect(coerce('hello', 'text')).toBe('hello')
  })
  it('keeps toggles boolean', () => {
    expect(coerce(true, 'toggle')).toBe(true)
    expect(coerce(false, 'toggle')).toBe(false)
  })
})

describe('SETTINGS_FIELDS', () => {
  it('every field has a key, label, group and type', () => {
    for (const f of SETTINGS_FIELDS) {
      expect(f.key).toBeTruthy()
      expect(f.label).toBeTruthy()
      expect(f.group).toBeTruthy()
      expect(['text', 'password', 'number', 'toggle', 'select']).toContain(f.type)
    }
  })
})
