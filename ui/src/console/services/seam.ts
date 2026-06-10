// Service seam: the single place the console talks to the real daemon.
// Wraps the shared ui/src/lib/api client so console pages depend on one
// surface and can fall back to demo data when the daemon is unreachable.

import { api, openStateStream, openLogStream, openAudioStream } from '@/lib/api'
import type { VoiceStatePayload, LogPayload, AudioTelemetryPayload } from '@/lib/api'

export { api, openStateStream, openLogStream, openAudioStream }
export type { VoiceStatePayload, LogPayload, AudioTelemetryPayload }

// Same-origin when served by the daemon (port 38130); otherwise the dev
// server (Vite on 3000) points at the loopback daemon.
const BASE =
  typeof window !== 'undefined' && window.location.port === '38130'
    ? ''
    : 'http://127.0.0.1:38130'

export interface VersionInfo {
  version: string
  channel: string
}

export async function fetchVersion(): Promise<VersionInfo> {
  try {
    const r = await fetch(`${BASE}/api/version`)
    if (!r.ok) return { version: 'dev', channel: 'develop' }
    return (await r.json()) as VersionInfo
  } catch {
    return { version: 'dev', channel: 'develop' }
  }
}
