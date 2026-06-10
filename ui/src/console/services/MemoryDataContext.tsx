import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { MemoryNode, CategoryDef } from '@/console/types/graph'
import type { Reminder, EpisodicMemory } from '@/console/types'
import { memoryApi } from './memoryApi'
import { mapGraphData, mapReminders, mapEpisodic, STANDARD_CATEGORIES } from '@/console/lib/memoryMap'

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
  rescheduleReminder: (id: string, date: string, time: string) => Promise<void>
  setReminderStatus: (id: string, status: 'completed' | 'cancelled') => Promise<void>
  /** Fetch the full node (incl. its data/facts) for the detail editor. */
  fetchNodeData: (id: string) => Promise<string>
  saveNodeData: (id: string, data: string) => Promise<void>
  deleteNode: (id: string) => Promise<void>
}

function isoFrom(date: string, time: string): string {
  // Interpret as local wall-clock; toISOString normalises to UTC for the API.
  const d = new Date(`${date}T${time || '12:00'}:00`)
  return d.toISOString()
}

function useMemoryData(): MemoryData {
  const [live, setLive] = useState(false)
  const [graphNodes, setGraphNodes] = useState<MemoryNode[]>([])
  const [categories, setCategories] = useState<CategoryDef[]>(STANDARD_CATEGORIES)
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [episodic, setEpisodic] = useState<EpisodicMemory[]>([])

  // Real data only — when the daemon is unreachable or the graph is empty we
  // show the honest empty state, never demo memories (data privacy first).
  const load = useCallback(async () => {
    try {
      const graph = await memoryApi.graph()
      const mapped = mapGraphData(graph)
      setGraphNodes(mapped.nodes)
      setCategories(mapped.categories.length ? mapped.categories : STANDARD_CATEGORIES)
      setLive(true)
    } catch {
      setLive(false)
    }
    try {
      setReminders(mapReminders(await memoryApi.reminders()))
    } catch {
      /* keep current */
    }
    try {
      setEpisodic(mapEpisodic(await memoryApi.episodic()))
    } catch {
      /* keep current */
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
  const rescheduleReminder = useCallback(
    async (id: string, date: string, time: string) => {
      await memoryApi.updateReminder(id, { status: 'pending', trigger_at: isoFrom(date, time) })
      await reloadReminders()
    },
    [reloadReminders],
  )
  const setReminderStatus = useCallback(
    async (id: string, status: 'completed' | 'cancelled') => {
      await memoryApi.updateReminder(id, { status })
      await reloadReminders()
    },
    [reloadReminders],
  )

  const fetchNodeData = useCallback(async (id: string) => {
    const res = await memoryApi.node(id)
    const data = (res.node as { data?: unknown }).data
    return typeof data === 'string' ? data : ''
  }, [])
  const saveNodeData = useCallback(
    async (id: string, data: string) => {
      await memoryApi.updateNode(id, { data })
      await load()
    },
    [load],
  )
  const deleteNode = useCallback(
    async (id: string) => {
      await memoryApi.deleteNode(id)
      await load()
    },
    [load],
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
    rescheduleReminder,
    setReminderStatus,
    fetchNodeData,
    saveNodeData,
    deleteNode,
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
