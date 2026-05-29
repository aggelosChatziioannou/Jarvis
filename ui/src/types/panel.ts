export type PanelTab =
  | 'live-logs'
  | 'audio-io'
  | 'wake-word'
  | 'voice-tts'
  | 'language-model'
  | 'mcp-servers'
  | 'api-keys'
  | 'easter-eggs';

export interface TabConfig {
  id: PanelTab;
  label: string;
  icon: string;
}

export const TABS: TabConfig[] = [
  { id: 'live-logs', label: 'Live Logs', icon: 'ScrollText' },
  { id: 'audio-io', label: 'Audio I/O', icon: 'Mic' },
  { id: 'wake-word', label: 'Wake Word', icon: 'Ear' },
  { id: 'voice-tts', label: 'Voice (TTS)', icon: 'Volume2' },
  { id: 'language-model', label: 'Language Model', icon: 'Brain' },
  { id: 'mcp-servers', label: 'Services', icon: 'Server' },
  { id: 'api-keys', label: 'API Keys', icon: 'Key' },
  { id: 'easter-eggs', label: 'Easter Eggs', icon: 'Film' },
];

export interface LogEntry {
  id: string;
  timestamp: string;
  level: 'info' | 'warning' | 'error' | 'fast-path' | 'mcp' | 'easter-egg';
  message: string;
}

export interface MCPServer {
  id: string;
  name: string;
  description: string;
  icon: string;
  status: 'connected' | 'disconnected';
  enabled: boolean;
}

export interface MemoryEntry {
  id: string;
  timestamp: string;
  snippet: string;
}

export interface FastPathEntry {
  id: string;
  pattern: string;
  tool: string;
  response: string;
}

export interface EasterEggEntry {
  id: string;
  name: string;
  triggers: string[];
  description: string;
  enabled: boolean;
}

export interface ApiKeyField {
  id: string;
  label: string;
  value: string;
  type: 'text' | 'email' | 'password';
}
