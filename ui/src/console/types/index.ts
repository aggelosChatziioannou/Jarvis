export type Category = 'Identity' | 'Preferences' | 'Events' | 'Directives' | 'Health';

export interface GraphNode {
  id: string;
  label: string;
  category: Category;
  importance: number;
  confidence: number;
  permanent: boolean;
  ttl?: number;
  emphasis: number;
  recentlyChanged: boolean;
  value?: string;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

export interface GraphConnection {
  source: string;
  target: string;
  strength: number;
}

export interface Reminder {
  id: string;
  title: string;
  time: string;
  date: string;
  status: 'pending' | 'completed' | 'snoozed' | 'cancelled';
  recurring?: boolean;
  category?: Category;
}

export interface EpisodicMemory {
  id: string;
  date: string;
  content: string;
}

export interface MemoryVersion {
  value: string;
  timestamp: string;
  reason?: string;
}

export interface MemoryHistory {
  nodeId: string;
  versions: MemoryVersion[];
}

export const CATEGORY_COLORS: Record<Category, string> = {
  Identity: '#38bdf8',
  Preferences: '#a78bfa',
  Events: '#fbbf24',
  Directives: '#34d399',
  Health: '#fb7185',
};
