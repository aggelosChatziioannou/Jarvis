// Centralised API client for the Jarvis daemon backend.
// All HTTP/WebSocket I/O lives here; tabs just call these functions.

const BASE = (() => {
  // When the UI is served *by* the daemon (built static), use same origin.
  // When run via Vite dev server (port 5173), point at the daemon on 38130.
  if (typeof window !== 'undefined' && window.location.port === '38130') {
    return '';
  }
  return 'http://127.0.0.1:38130';
})();

const WS_BASE = BASE.replace(/^http/, 'ws') || `ws://${window.location.host}`;

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

async function jpost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

async function jpatch<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

async function jdel<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

// ---------- Types ----------

export interface VoiceStatePayload {
  state: 'idle' | 'listening' | 'thinking' | 'synthesizing' | 'speaking';
  isMuted: boolean;
  uptime: number;
  lastWake: string | null;
  commandsProcessed: number;
  query?: string;
  // Monotonic counter bumped by the Core Audio device watcher on any
  // add/remove/state/default change. Clients re-fetch the device list when it
  // increments. Absent until the daemon has published at least one change.
  devices_changed?: number;
}

export interface LogPayload {
  id: string;
  timestamp: string;
  level: 'info' | 'warning' | 'error' | 'fast-path' | 'mcp' | 'easter-egg';
  message: string;
}

export interface MCPInfo {
  id: string;
  name: string;
  description: string;
  version: string;
  enabled: boolean;
  status: 'connected' | 'disconnected';
}

export interface MemoryItem {
  id: string;
  timestamp: string;
  snippet: string;
}

export interface FastPathInfo {
  id: string;
  pattern: string;
  tool: string;
  response: string;
}

export interface EasterEgg {
  id: string;
  name: string;
  triggers: string[];
  description: string;
  enabled: boolean;
}

export interface AudioDevice {
  id: string; // stable Windows Core Audio endpoint id
  name: string; // friendly name (display + fallback match)
  is_default: boolean; // current OS default for its direction
  available: boolean; // endpoint is currently Active (plugged in)
}

export interface AudioDevices {
  inputs: AudioDevice[];
  outputs: AudioDevice[];
}

export interface TTSCacheStats {
  hits: number;
  misses: number;
  size_bytes: number;
  count: number;
}

// ---------- Endpoints ----------

export const api = {
  // health + state
  health: () => jget<{ ok: boolean; uptime: number; buffer_size: number }>('/api/health'),
  state: () => jget<VoiceStatePayload>('/api/state'),

  // commands
  stop: () => jpost<{ ok: boolean; response: string | null }>('/api/command/stop'),
  mute: () => jpost<{ ok: boolean; response: string | null }>('/api/command/mute'),
  unmute: () => jpost<{ ok: boolean; response: string | null }>('/api/command/unmute'),
  triggerNow: () => jpost<{ ok: boolean; response: string | null }>('/api/command/trigger'),

  // config
  getConfig: () => jget<Record<string, unknown>>('/api/config'),
  patchConfig: (updates: Record<string, unknown>) =>
    jpatch<Record<string, unknown>>('/api/config', { updates }),

  // logs
  logs: (limit = 500) => jget<LogPayload[]>(`/api/logs?limit=${limit}`),
  clearLogs: () => jdel<{ ok: boolean }>('/api/logs'),

  // MCPs
  mcps: () => jget<MCPInfo[]>('/api/mcps'),
  toggleMcp: (id: string, enabled: boolean) =>
    jpatch<{ id: string; enabled: boolean }>(`/api/mcps/${id}`, { enabled }),

  // memory
  memory: (q?: string, limit = 50) =>
    jget<MemoryItem[]>(`/api/memory?${q ? `q=${encodeURIComponent(q)}&` : ''}limit=${limit}`),
  clearMemory: () => jdel<{ ok: boolean }>('/api/memory'),

  // fast paths
  fastpaths: () => jget<FastPathInfo[]>('/api/fastpaths'),

  // easter eggs
  eastereggs: () => jget<EasterEgg[]>('/api/eastereggs'),
  toggleEgg: (id: string, enabled: boolean) =>
    jpatch<{ id: string; enabled: boolean }>(`/api/eastereggs/${id}`, { enabled }),

  // LLM
  llmModels: () =>
    jget<{ name: string; size: number; modified?: string }[]>('/api/llm/models'),

  // Audio
  audioDevices: () => jget<AudioDevices>('/api/audio/devices'),
  testTone: () => jpost<{ ok: boolean }>('/api/audio/test-tone'),

  // TTS cache
  ttsCacheStats: () => jget<TTSCacheStats>('/api/tts/cache'),
  clearTTSCache: () => jdel<{ ok: boolean }>('/api/tts/cache'),
};

// ---------- WebSockets ----------

export function openLogStream(onLog: (log: LogPayload) => void): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let reconnectTimer: number | null = null;

  const connect = () => {
    if (closed) return;
    try {
      ws = new WebSocket(`${WS_BASE}/ws/logs`);
      ws.onmessage = (e) => {
        try {
          onLog(JSON.parse(e.data));
        } catch {
          /* ignore */
        }
      };
      ws.onclose = () => {
        if (!closed) {
          reconnectTimer = window.setTimeout(connect, 1500);
        }
      };
      ws.onerror = () => {
        try {
          ws?.close();
        } catch {
          /* ignore */
        }
      };
    } catch {
      reconnectTimer = window.setTimeout(connect, 1500);
    }
  };

  connect();
  return () => {
    closed = true;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    try {
      ws?.close();
    } catch {
      /* ignore */
    }
  };
}

export function openStateStream(onState: (s: VoiceStatePayload) => void): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let reconnectTimer: number | null = null;

  const connect = () => {
    if (closed) return;
    try {
      ws = new WebSocket(`${WS_BASE}/ws/state`);
      ws.onmessage = (e) => {
        try {
          onState(JSON.parse(e.data));
        } catch {
          /* ignore */
        }
      };
      ws.onclose = () => {
        if (!closed) {
          reconnectTimer = window.setTimeout(connect, 1500);
        }
      };
      ws.onerror = () => {
        try {
          ws?.close();
        } catch {
          /* ignore */
        }
      };
    } catch {
      reconnectTimer = window.setTimeout(connect, 1500);
    }
  };

  connect();
  return () => {
    closed = true;
    if (reconnectTimer) window.clearTimeout(reconnectTimer);
    try {
      ws?.close();
    } catch {
      /* ignore */
    }
  };
}
