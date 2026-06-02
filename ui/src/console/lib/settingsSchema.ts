// Curated subset of the daemon config exposed in the console Settings tab.
// The full config is large; this surfaces the high-value knobs. Audio-specific
// knobs (devices, VAD/wake thresholds) live on the Audio page, not here.

export type FieldType = 'text' | 'password' | 'number' | 'toggle' | 'select'

export interface SettingsField {
  key: string
  label: string
  group: string
  type: FieldType
  /** Static options for a select. */
  options?: string[]
  /** Populate the select from a live source (e.g. installed Ollama models). */
  dynamicOptions?: 'models'
  hint?: string
}

export const SETTINGS_FIELDS: SettingsField[] = [
  { key: 'ollama_chat_model', label: 'Chat model', group: 'Language Model', type: 'select', dynamicOptions: 'models' },
  { key: 'intent_judge_model', label: 'Intent judge model', group: 'Language Model', type: 'select', dynamicOptions: 'models' },
  { key: 'tool_router_model', label: 'Tool router model', group: 'Language Model', type: 'select', dynamicOptions: 'models' },

  { key: 'stt_backend', label: 'Speech-to-text backend', group: 'Speech', type: 'select', options: ['wispr', 'whisper'] },
  { key: 'whisper_default_language', label: 'Default language', group: 'Speech', type: 'text', hint: 'e.g. en, el (local Whisper only)' },

  { key: 'reminders_enabled', label: 'Reminders enabled', group: 'Behaviour', type: 'toggle' },
  { key: 'voice_debug', label: 'Verbose debug logs', group: 'Behaviour', type: 'toggle' },
  { key: 'hot_window_seconds', label: 'Follow-up window (s)', group: 'Behaviour', type: 'number', hint: 'Wake-free follow-up after a reply' },

  { key: 'brave_search_api_key', label: 'Brave Search API key', group: 'API Keys', type: 'password', hint: 'Optional; enables Brave web search' },
]

export function coerce(raw: unknown, type: FieldType): string | number | boolean {
  if (type === 'number') {
    const n = Number(raw)
    return Number.isFinite(n) ? n : 0
  }
  if (type === 'toggle') return Boolean(raw)
  return raw == null ? '' : String(raw)
}

/** Keys whose edited value differs from the original (deep-equal by JSON). */
export function settingsDiff(
  original: Record<string, unknown>,
  edited: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const k of Object.keys(edited)) {
    if (JSON.stringify(edited[k]) !== JSON.stringify(original[k])) out[k] = edited[k]
  }
  return out
}
