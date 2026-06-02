// Daemon fetchers for the Memory page (graph + reminders + diary summaries).
// Kept in the console module so the page depends on one surface.

import type { RawGraphData, RawReminder, RawMemoryItem } from '@/console/lib/memoryMap'

const BASE =
  typeof window !== 'undefined' && window.location.port === '38130'
    ? ''
    : 'http://127.0.0.1:38130'

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, init)
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

function body(method: string, payload: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }
}

export interface ReminderCreateBody {
  text: string
  trigger_at: string
  recurring_rule?: string | null
}

export interface ReminderUpdateBody {
  status?: string
  snooze_until?: string
  trigger_at?: string
}

export const memoryApi = {
  graph: () => j<RawGraphData>('/api/graph/nodes'),
  node: (id: string) =>
    j<{ node: Record<string, unknown>; children: unknown[]; ancestors: unknown[] }>(
      `/api/graph/node/${encodeURIComponent(id)}`,
    ),
  updateNode: (id: string, payload: { name?: string; description?: string; data?: string }) =>
    j(`/api/graph/node/${encodeURIComponent(id)}`, body('PUT', payload)),
  deleteNode: (id: string) => j(`/api/graph/node/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  reminders: () => j<RawReminder[]>('/api/reminders'),
  createReminder: (payload: ReminderCreateBody) => j<RawReminder>('/api/reminders', body('POST', payload)),
  updateReminder: (id: string, payload: ReminderUpdateBody) =>
    j<RawReminder>(`/api/reminders/${encodeURIComponent(id)}`, body('PUT', payload)),
  deleteReminder: (id: string) =>
    j(`/api/reminders/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  episodic: () => j<RawMemoryItem[]>('/api/memory?limit=50'),
}
