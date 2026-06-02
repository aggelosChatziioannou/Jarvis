import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { MemoryNode, CategoryDef } from '@/console/types/graph'
import type { Reminder, EpisodicMemory } from '@/console/types'
import { memoryApi } from './memoryApi'
import { mapGraphData, mapReminders, mapEpisodic, STANDARD_CATEGORIES } from '@/console/lib/memoryMap'
import { memoryNodes as MOCK_NODES, categories as MOCK_CATEGORIES } from '@/console/data/graphMock'
import { sampleReminders as MOCK_REMINDERS, sampleEpisodic as MOCK_EPISODIC } from '@/console/data/demo'

export interface MemoryData {
  /** True once real daemon data loaded; false while on demo/mock fallback. */
  live: boolean
  graphNodes: MemoryNode[]
  categories: CategoryDef[]
  reminders: Reminder[]
  episodic: EpisodicMemory[]
  reload: () => void
  createReminder: (title: string, date: string, time: string) => Promise<void>
  completeReminder: (id: string) => Promise<void>
  snoozeReminder: (id: string) => Promise<void>
  deleteReminder: (id: string) => Promise<void>
}

function isoFrom(date: string, time: string): string {
  // Interpret as local wall-clock; toISOString normalises to UTC for the API.
  const d = new Date(`${date}T${time || '12:00'}:00`)
  return d.toISOString()
}

function useMemoryData(): MemoryData {
  const [live, setLive] = useState(false)
  const [graphNodes, setGraphNodes] = useState<MemoryNode[]>(MOCK_NODES)
  const [categories, setCategories] = useState<CategoryDef[]>(MOCK_CATEGORIES)
  const [reminders, setReminders] = useState<Reminder[]>(MOCK_REMINDERS)
  const [episodic, setEpisodic] = useState<EpisodicMemory[]>(MOCK_EPISODIC)

  const load = useCallback(async () => {
    try {
      const graph = await memoryApi.graph()
      const mapped = mapGraphData(graph)
      setGraphNodes(mapped.nodes.length ? mapped.nodes : MOCK_NODES)
      setCategories(mapped.categories.length ? mapped.categories : STANDARD_CATEGORIES)
      setLive(true)
    } catch {
      setGraphNodes(MOCK_NODES)
      setCategories(MOCK_CATEGORIES)
    }
    try {
      setReminders(mapReminders(await memoryApi.reminders()))
    } catch {
      setReminders(MOCK_REMINDERS)
    }
    try {
      setEpisodic(mapEpisodic(await memoryApi.episodic()))
    } catch {
      setEpisodic(MOCK_EPISODIC)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const reloadReminders = useCallback(async () => {
    try {
      setReminders(mapReminders(await memoryApi.reminders()))
    } catch {
      /* keep current */
    }
  }, [])

  const createReminder = useCallback(
    async (title: string, date: string, time: string) => {
      await memoryApi.createReminder({ text: title, trigger_at: isoFrom(date, time) })
      await reloadReminders()
    },
    [reloadReminders],
  )
  const completeReminder = useCallback(
    async (id: string) => {
      await memoryApi.updateReminder(id, { status: 'completed' })
      await reloadReminders()
    },
    [reloadReminders],
  )
  const snoozeReminder = useCallback(
    async (id: string) => {
      const until = new Date(Date.now() + 10 * 60 * 1000).toISOString()
      await memoryApi.updateReminder(id, { status: 'snoozed', snooze_until: until })
      await reloadReminders()
    },
    [reloadReminders],
  )
  const deleteReminder = useCallback(
    async (id: string) => {
      await memoryApi.deleteReminder(id)
      await reloadReminders()
    },
    [reloadReminders],
  )

  return {
    live,
    graphNodes,
    categories,
    reminders,
    episodic,
    reload: () => void load(),
    createReminder,
    completeReminder,
    snoozeReminder,
    deleteReminder,
  }
}

const Ctx = createContext<MemoryData | null>(null)

export function MemoryDataProvider({ children }: { children: ReactNode }) {
  return <Ctx.Provider value={useMemoryData()}>{children}</Ctx.Provider>
}

export function useMemoryDataCtx(): MemoryData {
  const v = useContext(Ctx)
  if (!v) throw new Error('useMemoryDataCtx must be used within <MemoryDataProvider>')
  return v
}
