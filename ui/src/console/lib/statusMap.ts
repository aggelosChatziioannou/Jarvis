import type { VoiceStatePayload } from '@/lib/api'

export interface StatusDisplay {
  label: string
  color: string
}

// Voice state -> StatusBar label + dot colour. Colours match the console palette.
const STATUS_STYLES: Record<string, StatusDisplay> = {
  idle: { label: 'Idle', color: '#34d399' },
  listening: { label: 'Listening', color: '#22d3ee' },
  thinking: { label: 'Thinking', color: '#fbbf24' },
  synthesizing: { label: 'Thinking', color: '#fbbf24' },
  speaking: { label: 'Speaking', color: '#22d3ee' },
}

const OFFLINE: StatusDisplay = { label: 'Offline', color: '#475569' }
const MUTED: StatusDisplay = { label: 'Muted', color: '#fb7185' }

/**
 * Resolve the StatusBar label + colour from the live connection.
 * Pure and exhaustively defaulted so the bar never renders blank.
 */
export function statusDisplay(
  state: Pick<VoiceStatePayload, 'state' | 'isMuted'> | null,
  connected: boolean,
): StatusDisplay {
  if (!connected) return OFFLINE
  if (state?.isMuted) return MUTED
  return STATUS_STYLES[state?.state ?? 'idle'] ?? STATUS_STYLES.idle
}
