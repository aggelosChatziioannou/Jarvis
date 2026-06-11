import { describe, it, expect } from 'vitest'
import { mapGraphData, mapReminders, mapEpisodic, branchCategory, adaptToGraphNode } from './memoryMap'
import type { MemoryNode } from '@/console/types/graph'

describe('branchCategory', () => {
  it('maps the real fixed branches to console categories', () => {
    expect(branchCategory('user')).toBe('identity')
    expect(branchCategory('directives')).toBe('directives')
    expect(branchCategory('world')).toBe('events')
  })
  it('falls back for unknown branches', () => {
    expect(branchCategory('whatever')).toBe('preferences')
  })
})

describe('mapGraphData', () => {
  const graph = {
    nodes: [
      { id: 'root', name: 'You', description: '', parent_id: null, depth: 0, data_token_count: 0, access_count: 0 },
      { id: 'user', name: 'User', description: 'about you', parent_id: 'root', depth: 1, data_token_count: 5, access_count: 1 },
      { id: 'world', name: 'World', description: 'facts', parent_id: 'root', depth: 1, data_token_count: 2, access_count: 0 },
      { id: 'n1', name: 'Coffee', description: 'black no sugar', parent_id: 'user', depth: 2, data_token_count: 3, access_count: 2 },
      { id: 'n2', name: 'Sushi', description: 'likes sushi', parent_id: 'n1', depth: 3, data_token_count: 1, access_count: 0 },
    ],
    edges: [],
  }

  it('produces one central node from root', () => {
    const { nodes } = mapGraphData(graph)
    const central = nodes.filter((n) => n.type === 'central')
    expect(central).toHaveLength(1)
    expect(central[0].id).toBe('root')
    expect(central[0].label).toBe('YOU')
  })

  it('turns depth-1 branches into category hubs with cat-<type> ids', () => {
    const { nodes } = mapGraphData(graph)
    const cats = nodes.filter((n) => n.type === 'category')
    const ids = cats.map((c) => c.id)
    expect(ids).toContain('cat-identity') // user
    expect(ids).toContain('cat-events') // world
  })

  it('keeps depth>=2 nodes as clusters with the real hierarchy preserved', () => {
    const { nodes } = mapGraphData(graph)
    const clusters = nodes.filter((n) => n.type === 'cluster')
    const coffee = clusters.find((l) => l.id === 'n1')
    const sushi = clusters.find((l) => l.id === 'n2')
    expect(coffee?.parentId).toBe('cat-identity') // child of the user branch hub
    expect(coffee?.value).toBe('black no sugar')
    expect(sushi?.parentId).toBe('n1') // deep node keeps its REAL parent
    expect(coffee?.category).toBe('identity')
  })

  it('returns the five standard categories for colouring', () => {
    const { categories } = mapGraphData(graph)
    expect(categories.map((c) => c.type)).toEqual([
      'identity', 'preferences', 'events', 'directives', 'health',
    ])
  })
})

describe('mapReminders', () => {
  it('maps backend reminders to the console shape', () => {
    const out = mapReminders([
      {
        id: 'r1',
        text: 'Call mum',
        trigger_at: '2026-06-03T17:30:00+00:00',
        recurring_rule: null,
        status: 'pending',
        snooze_until: null,
        created_at: '2026-06-02T10:00:00+00:00',
        source: 'console',
      },
    ])
    expect(out[0].id).toBe('r1')
    expect(out[0].title).toBe('Call mum')
    expect(out[0].status).toBe('pending')
    expect(out[0].recurring).toBe(false)
    // date/time are derived from trigger_at (local); format shape only
    expect(out[0].date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(out[0].time).toMatch(/^\d{2}:\d{2}$/)
  })

  it('marks recurring when a rule is present and folds missed -> cancelled', () => {
    const out = mapReminders([
      { id: 'r2', text: 'Standup', trigger_at: '2026-06-03T09:00:00+00:00', recurring_rule: '0 9 * * 1-5', status: 'missed', snooze_until: null, created_at: '', source: 'voice' },
    ])
    expect(out[0].recurring).toBe(true)
    expect(out[0].status).toBe('cancelled')
  })
})

describe('adaptToGraphNode', () => {
  it('adapts the graph node model to the detail-panel model', () => {
    const m: MemoryNode = {
      id: 'n1', type: 'memory', label: 'Coffee', category: 'identity',
      importance: 8, confidence: 100, value: 'black no sugar',
    }
    const g = adaptToGraphNode(m)
    expect(g.id).toBe('n1')
    expect(g.category).toBe('Identity') // capitalised
    expect(g.importance).toBeCloseTo(0.8) // 0..1 scale
    expect(g.confidence).toBeCloseTo(1.0)
    expect(g.value).toBe('black no sugar')
  })
})

describe('mapEpisodic', () => {
  it('maps diary summaries to episodic memories', () => {
    const out = mapEpisodic([
      { id: 'm1', timestamp: '2026-05-28T20:00:00+00:00', snippet: 'User was sick' },
    ])
    expect(out[0].id).toBe('m1')
    expect(out[0].content).toBe('User was sick')
    expect(out[0].date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})

describe('per-fact graph mapping (facts live as data lines)', () => {
  const graph = {
    nodes: [
      { id: 'root', name: 'Root', description: '', parent_id: null, depth: 0, facts: [], fact_count: 0 },
      {
        id: 'user', name: 'User', description: '', parent_id: 'root', depth: 1,
        facts: ['The user is named Aggelos.', 'The user lives in Ioannina, Greece.'], fact_count: 2,
      },
      {
        id: 'directives', name: 'Directives', description: '', parent_id: 'root', depth: 1,
        facts: ['The user instructed the assistant to always reply in English.'], fact_count: 1,
      },
      { id: 'world', name: 'World', description: '', parent_id: 'root', depth: 1, facts: [], fact_count: 0 },
    ],
    edges: [],
  }

  it('renders each fact line as its own memory dot with the full line as value', async () => {
    const { mapGraphData } = await import('./memoryMap')
    const { nodes } = mapGraphData(graph)
    const memories = nodes.filter((n) => n.type === 'memory')
    expect(memories).toHaveLength(3)
    expect(memories[0].id).toBe('user#0')
    expect(memories[0].value).toBe('The user is named Aggelos.')
    expect(memories[0].category).toBe('identity')
    expect(memories[2].category).toBe('directives')
  })

  it('category hubs count facts, not container nodes', async () => {
    const { mapGraphData } = await import('./memoryMap')
    const { nodes } = mapGraphData(graph)
    const identity = nodes.find((n) => n.id === 'cat-identity')
    expect(identity?.subtitle).toBe('2 memories')
    const directives = nodes.find((n) => n.id === 'cat-directives')
    expect(directives?.subtitle).toBe('1 memory')
  })
})

describe('fact id + line-edit helpers', () => {
  it('parseFactId round-trips and leaves real node ids alone', async () => {
    const { makeFactId, parseFactId } = await import('./memoryMap')
    expect(parseFactId(makeFactId('user', 3))).toEqual({ nodeId: 'user', factIndex: 3 })
    expect(parseFactId('a-real-uuid')).toEqual({ nodeId: 'a-real-uuid', factIndex: null })
  })

  it('replaceFactLine edits exactly one fact', async () => {
    const { replaceFactLine } = await import('./memoryMap')
    expect(replaceFactLine('a\nb\nc', 1, 'B!')).toBe('a\nB!\nc')
    expect(replaceFactLine('a\nb', 5, 'x')).toBe('a\nb') // out of range: unchanged
    expect(replaceFactLine('a\nb\nc', 1, '   ')).toBe('a\nc') // emptied = removed
  })

  it('removeFactLine deletes exactly one fact, never the node', async () => {
    const { removeFactLine } = await import('./memoryMap')
    expect(removeFactLine('a\nb\nc', 0)).toBe('b\nc')
    expect(removeFactLine('a', 0)).toBe('')
  })

  it('factLabel strips boilerplate and truncates', async () => {
    const { factLabel } = await import('./memoryMap')
    expect(factLabel('The user is named Aggelos.')).toBe('Is named Aggelos')
    expect(factLabel("The user's favourite foods are Greek cuisine, burgers, pizza, and pasta.").length).toBeLessThanOrEqual(43)
  })
})

describe('cluster subtree counts', () => {
  it('hub badge counts every fact in its subtree, cluster badge its own', async () => {
    const { mapGraphData } = await import('./memoryMap')
    const { nodes } = mapGraphData({
      nodes: [
        { id: 'root', name: 'Root', description: '', parent_id: null, depth: 0, facts: [], fact_count: 0 },
        { id: 'user', name: 'User', description: '', parent_id: 'root', depth: 1, facts: ['direct fact'], fact_count: 1 },
        { id: 'c1', name: 'Identity', description: 'who', parent_id: 'user', depth: 2, facts: ['a', 'b'], fact_count: 2 },
      ],
      edges: [],
    })
    expect(nodes.find((n) => n.id === 'cat-identity')?.subtitle).toBe('3 memories')
    const cluster = nodes.find((n) => n.id === 'c1')
    expect(cluster?.type).toBe('cluster')
    expect(cluster?.subtitle).toBe('2')
    // facts parented correctly: direct fact under the hub, others under c1
    expect(nodes.find((n) => n.id === 'user#0')?.parentId).toBe('cat-identity')
    expect(nodes.find((n) => n.id === 'c1#0')?.parentId).toBe('c1')
  })
})
