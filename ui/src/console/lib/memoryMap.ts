// Maps the real daemon memory data into the console's display shapes.
//
// The graph view is a 2-level radial (central -> categories -> leaves), but the
// real graph is the 3 fixed branches (user/directives/world) with arbitrary
// depth. We map root -> central, each depth-1 branch -> a category hub, and
// flatten every deeper node into a memory leaf under its branch's category.
// Node ids are preserved on leaves so selection can fetch the real node.

import type { MemoryNode, CategoryType, CategoryDef } from '@/console/types/graph'
import type { Reminder, EpisodicMemory, GraphNode, Category } from '@/console/types'

export const STANDARD_CATEGORIES: CategoryDef[] = [
  { type: 'identity', label: 'Identity', color: '#38bdf8', glow: 'rgba(56, 189, 248, 0.12)' },
  { type: 'preferences', label: 'Preferences', color: '#a78bfa', glow: 'rgba(167, 139, 250, 0.12)' },
  { type: 'events', label: 'Events', color: '#fbbf24', glow: 'rgba(251, 191, 36, 0.12)' },
  { type: 'directives', label: 'Directives', color: '#34d399', glow: 'rgba(52, 211, 153, 0.12)' },
  { type: 'health', label: 'Health', color: '#fb7185', glow: 'rgba(251, 113, 133, 0.12)' },
]

const BRANCH_CATEGORY: Record<string, CategoryType> = {
  user: 'identity',
  directives: 'directives',
  world: 'events',
}

export function branchCategory(branchId: string): CategoryType {
  return BRANCH_CATEGORY[branchId] ?? 'preferences'
}

export interface RawGraphNode {
  id: string
  name: string
  description: string
  parent_id: string | null
  depth: number
  data_token_count?: number
  access_count?: number
  /** Non-empty data lines — each line is one remembered fact (graph v2). */
  facts?: string[]
  fact_count?: number
}

// ── Per-fact synthetic ids ─────────────────────────────────────────────────
// Facts live as lines inside a node's data, so a single fact is addressed as
// "<nodeId>#<lineIndex>". The data context resolves these back to the real
// node for fetch/save/delete (line-level edits via PUT of the full data).

const FACT_SEP = '#'

export function makeFactId(nodeId: string, index: number): string {
  return `${nodeId}${FACT_SEP}${index}`
}

export function parseFactId(id: string): { nodeId: string; factIndex: number | null } {
  const at = id.lastIndexOf(FACT_SEP)
  if (at < 0) return { nodeId: id, factIndex: null }
  const idx = Number(id.slice(at + 1))
  if (!Number.isInteger(idx) || idx < 0) return { nodeId: id, factIndex: null }
  return { nodeId: id.slice(0, at), factIndex: idx }
}

/** Normalise node data into its fact lines (matches the backend's split). */
export function factLines(data: string): string[] {
  return data.split('\n').map((l) => l.trim()).filter(Boolean)
}

export function replaceFactLine(data: string, index: number, newLine: string): string {
  const lines = factLines(data)
  if (index < 0 || index >= lines.length) return data
  const next = newLine.trim()
  if (next) lines[index] = next
  else lines.splice(index, 1) // emptied = removed
  return lines.join('\n')
}

export function removeFactLine(data: string, index: number): string {
  const lines = factLines(data)
  if (index < 0 || index >= lines.length) return data
  lines.splice(index, 1)
  return lines.join('\n')
}

/** Short display label for a fact line (the full line stays in `value`). */
export function factLabel(line: string): string {
  let s = line.trim().replace(/^the user'?s?\s+/i, '')
  s = s.charAt(0).toUpperCase() + s.slice(1)
  if (s.length > 42) s = `${s.slice(0, 42).trimEnd()}…`
  return s.replace(/\.$/, '')
}

export interface RawGraphData {
  nodes: RawGraphNode[]
  edges: { source: string; target: string }[]
}

function clampImportance(tokenCount: number): number {
  // No real "importance" in graph_data; approximate from content volume.
  if (tokenCount <= 0) return 4
  if (tokenCount < 50) return 6
  return 8
}

export function mapGraphData(graph: RawGraphData): { nodes: MemoryNode[]; categories: CategoryDef[] } {
  const byId = new Map<string, RawGraphNode>()
  for (const n of graph.nodes) byId.set(n.id, n)

  // Walk up to the depth-1 branch ancestor.
  function branchIdOf(n: RawGraphNode): string | null {
    let cur: RawGraphNode | undefined = n
    while (cur && cur.depth > 1) {
      cur = cur.parent_id ? byId.get(cur.parent_id) : undefined
    }
    return cur && cur.depth === 1 ? cur.id : null
  }

  const out: MemoryNode[] = []
  const childCount = new Map<CategoryType, number>()

  const root = graph.nodes.find((n) => n.id === 'root' || n.depth === 0)
  if (root) {
    out.push({
      id: root.id,
      type: 'central',
      label: 'YOU',
      subtitle: 'MEMORY CORE',
      category: 'identity',
      importance: 10,
      confidence: 100,
    })
  }

  // Memory leaves: every FACT (data line) of every node under a branch is
  // one memory dot. Nodes are containers in the v2 design — a single node
  // accumulates many facts before auto-split — so counting nodes would
  // show "0 memories" while Jarvis actually knows plenty.
  for (const n of graph.nodes) {
    if (n.depth < 1) continue
    const branch = n.depth === 1 ? n.id : branchIdOf(n)
    if (!branch) continue
    const cat = branchCategory(branch)
    const facts = n.facts ?? []
    for (let i = 0; i < facts.length; i++) {
      childCount.set(cat, (childCount.get(cat) ?? 0) + 1)
      out.push({
        id: makeFactId(n.id, i),
        type: 'memory',
        label: factLabel(facts[i]),
        category: cat,
        importance: 6,
        confidence: 100,
        value: facts[i],
        parentId: `cat-${cat}`,
      })
    }
    // Deeper nodes with no inline facts still render as a single memory so
    // legacy/structural leaves stay visible and selectable.
    if (n.depth >= 2 && facts.length === 0) {
      childCount.set(cat, (childCount.get(cat) ?? 0) + 1)
      out.push({
        id: n.id,
        type: 'memory',
        label: n.name,
        category: cat,
        importance: clampImportance(n.data_token_count ?? 0),
        confidence: 100,
        value: n.description || '',
        parentId: `cat-${cat}`,
      })
    }
  }

  // Category hubs from depth-1 branches.
  for (const n of graph.nodes) {
    if (n.depth !== 1) continue
    const cat = branchCategory(n.id)
    const count = childCount.get(cat) ?? 0
    out.push({
      id: `cat-${cat}`,
      type: 'category',
      label: n.name,
      subtitle: `${count} ${count === 1 ? 'memory' : 'memories'}`,
      category: cat,
      importance: 8,
      confidence: 100,
    })
  }

  return { nodes: out, categories: STANDARD_CATEGORIES }
}

// ── Reminders ──────────────────────────────────────────────────────────────

export interface RawReminder {
  id: string
  text: string
  trigger_at: string | null
  recurring_rule: string | null
  status: string
  snooze_until: string | null
  created_at: string | null
  source: string
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function localDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function localTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const STATUS_MAP: Record<string, Reminder['status']> = {
  pending: 'pending',
  completed: 'completed',
  snoozed: 'snoozed',
  cancelled: 'cancelled',
  missed: 'cancelled',
}

export function mapReminders(raw: RawReminder[]): Reminder[] {
  return raw.map((r) => ({
    id: r.id,
    title: r.text,
    date: localDate(r.trigger_at),
    time: localTime(r.trigger_at),
    status: STATUS_MAP[r.status] ?? 'pending',
    recurring: Boolean(r.recurring_rule),
  }))
}

// ── Episodic (diary summaries) ───────────────────────────────────────────────

export interface RawMemoryItem {
  id: string
  timestamp: string
  snippet: string
}

export function mapEpisodic(items: RawMemoryItem[]): EpisodicMemory[] {
  return items.map((m) => ({
    id: m.id,
    date: localDate(m.timestamp),
    content: m.snippet,
  }))
}

// ── Detail-panel adapter ─────────────────────────────────────────────────────
// The graph viz uses one node model (graph.ts MemoryNode); the detail panel uses
// another (index.ts GraphNode, capitalised category, 0..1 scales). Adapt on select.

const CAP_CATEGORY: Record<CategoryType, Category> = {
  identity: 'Identity',
  preferences: 'Preferences',
  events: 'Events',
  directives: 'Directives',
  health: 'Health',
}

export function adaptToGraphNode(m: MemoryNode): GraphNode {
  return {
    id: m.id,
    label: m.label,
    category: CAP_CATEGORY[m.category] ?? 'Preferences',
    importance: m.importance / 10,
    confidence: m.confidence / 100,
    permanent: m.permanent ?? false,
    emphasis: 0,
    recentlyChanged: m.recentlyChanged ?? false,
    value: m.value,
  }
}
