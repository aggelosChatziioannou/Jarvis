import type { MemoryNode, CategoryDef } from '@/console/types/graph';

export const categories: CategoryDef[] = [
  { type: 'identity', label: 'Identity', color: '#38bdf8', glow: 'rgba(56, 189, 248, 0.12)' },
  { type: 'preferences', label: 'Preferences', color: '#a78bfa', glow: 'rgba(167, 139, 250, 0.12)' },
  { type: 'events', label: 'Events', color: '#fbbf24', glow: 'rgba(251, 191, 36, 0.12)' },
  { type: 'directives', label: 'Directives', color: '#34d399', glow: 'rgba(52, 211, 153, 0.12)' },
  { type: 'health', label: 'Health', color: '#fb7185', glow: 'rgba(251, 113, 133, 0.12)' },
];

export const memoryNodes: MemoryNode[] = [
  // Central
  { id: 'you', type: 'central', label: 'YOU', subtitle: 'MEMORY CORE', category: 'identity', importance: 10, confidence: 100 },

  // Category hubs
  { id: 'cat-identity', type: 'category', label: 'Identity', subtitle: '6 memories', category: 'identity', importance: 8, confidence: 100, children: [] },
  { id: 'cat-preferences', type: 'category', label: 'Preferences', subtitle: '6 memories', category: 'preferences', importance: 8, confidence: 100, children: [] },
  { id: 'cat-events', type: 'category', label: 'Events', subtitle: '5 memories', category: 'events', importance: 8, confidence: 100, children: [] },
  { id: 'cat-directives', type: 'category', label: 'Directives', subtitle: '4 memories', category: 'directives', importance: 8, confidence: 100, children: [] },
  { id: 'cat-health', type: 'category', label: 'Health', subtitle: '5 memories', category: 'health', importance: 8, confidence: 100, children: [] },

  // Identity memories
  { id: 'mem-name', type: 'memory', label: 'Name', category: 'identity', importance: 9, confidence: 100, value: 'Alex', parentId: 'cat-identity' },
  { id: 'mem-occupation', type: 'memory', label: 'Occupation', category: 'identity', importance: 8, confidence: 95, value: 'Software Engineer', parentId: 'cat-identity' },
  { id: 'mem-location', type: 'memory', label: 'Work Location', category: 'identity', importance: 7, confidence: 90, value: 'Remote', parentId: 'cat-identity' },
  { id: 'mem-pronouns', type: 'memory', label: 'Pronouns', category: 'identity', importance: 6, confidence: 100, value: 'he/him', parentId: 'cat-identity' },
  { id: 'mem-age', type: 'memory', label: 'Age', category: 'identity', importance: 5, confidence: 95, value: '28', parentId: 'cat-identity' },
  { id: 'mem-preferred-name', type: 'memory', label: 'Preferred N.', category: 'identity', importance: 8, confidence: 100, value: 'Alexander', parentId: 'cat-identity' },

  // Preferences memories
  { id: 'mem-theme', type: 'memory', label: 'UI Theme', category: 'preferences', importance: 7, confidence: 100, value: 'Dark Mode', parentId: 'cat-preferences' },
  { id: 'mem-music', type: 'memory', label: 'Work Music', category: 'preferences', importance: 6, confidence: 85, value: 'Lo-fi / Ambient', parentId: 'cat-preferences' },
  { id: 'mem-coffee', type: 'memory', label: 'Coffee Order', category: 'preferences', importance: 5, confidence: 90, value: 'Black, no sugar', parentId: 'cat-preferences' },
  { id: 'mem-diet', type: 'memory', label: 'Dietary Res.', category: 'preferences', importance: 7, confidence: 100, value: 'Vegetarian', parentId: 'cat-preferences' },
  { id: 'mem-news', type: 'memory', label: 'News Sources', category: 'preferences', importance: 4, confidence: 75, value: 'TechCrunch, HN', parentId: 'cat-preferences' },
  { id: 'mem-interface', type: 'memory', label: 'Interface D.', category: 'preferences', importance: 8, confidence: 95, value: 'Keyboard-first', parentId: 'cat-preferences' },

  // Events memories
  { id: 'mem-standup', type: 'memory', label: 'Weekly Stan..', category: 'events', importance: 7, confidence: 100, value: 'Every Mon 10:00', parentId: 'cat-events' },
  { id: 'mem-birthday', type: 'memory', label: "Mom's Birth..", category: 'events', importance: 9, confidence: 100, value: 'March 15', parentId: 'cat-events' },
  { id: 'mem-tokyo', type: 'memory', label: 'Tokyo Trip', category: 'events', importance: 8, confidence: 80, value: '2025-04-10', parentId: 'cat-events' },
  { id: 'mem-design', type: 'memory', label: 'Design Crit..', category: 'events', importance: 6, confidence: 90, value: 'Every Fri 14:00', parentId: 'cat-events' },
  { id: 'mem-q2review', type: 'memory', label: 'Q2 Review D..', category: 'events', importance: 7, confidence: 95, value: '2025-06-30', parentId: 'cat-events' },

  // Directives memories
  { id: 'mem-focus', type: 'memory', label: 'Focus Hours', category: 'directives', importance: 8, confidence: 100, value: '09:00 - 12:00', parentId: 'cat-directives' },
  { id: 'mem-reminders', type: 'memory', label: 'Reminder St..', category: 'directives', importance: 6, confidence: 90, value: 'Enabled', parentId: 'cat-directives' },
  { id: 'mem-response', type: 'memory', label: 'Response Fo..', category: 'directives', importance: 7, confidence: 85, value: 'Concise, direct', parentId: 'cat-directives' },
  { id: 'mem-privacy', type: 'memory', label: 'Privacy Rule', category: 'directives', importance: 9, confidence: 100, value: 'Local-only mode', parentId: 'cat-directives' },

  // Health memories
  { id: 'mem-allergies', type: 'memory', label: 'Allergies', category: 'health', importance: 9, confidence: 100, value: 'Penicillin', parentId: 'cat-health' },
  { id: 'mem-sleep', type: 'memory', label: 'Sleep Sched..', category: 'health', importance: 7, confidence: 85, value: '23:00 - 07:00', parentId: 'cat-health' },
  { id: 'mem-exercise', type: 'memory', label: 'Exercise Ro..', category: 'health', importance: 6, confidence: 75, value: '3x / week', parentId: 'cat-health' },
  { id: 'mem-hydration', type: 'memory', label: 'Hydration G.', category: 'health', importance: 5, confidence: 90, value: '2.5L / day', parentId: 'cat-health' },
  { id: 'mem-posture', type: 'memory', label: 'Posture Rem..', category: 'health', importance: 4, confidence: 80, value: 'Every 30min', parentId: 'cat-health' },
];

// Populate children arrays on category nodes
memoryNodes.forEach((n) => {
  if (n.type === 'memory' && n.parentId) {
    const parent = memoryNodes.find((p) => p.id === n.parentId);
    if (parent) {
      parent.children = parent.children || [];
      parent.children.push(n.id);
    }
  }
});
