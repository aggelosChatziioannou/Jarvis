export type CategoryType = 'identity' | 'preferences' | 'events' | 'directives' | 'health';

export interface MemoryNode {
  id: string;
  type: 'central' | 'category' | 'cluster' | 'memory';
  label: string;
  subtitle?: string;
  category: CategoryType;
  importance: number;
  confidence: number;
  value?: string;
  parentId?: string;
  children?: string[];
  permanent?: boolean;
  recentlyChanged?: boolean;
}

export interface CategoryDef {
  type: CategoryType;
  label: string;
  color: string;
  glow: string;
}
