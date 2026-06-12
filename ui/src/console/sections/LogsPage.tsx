import { useMemo, useState, useCallback } from 'react'
import type { LogLevel, LogSource } from '@/console/types/logs'
import { useLiveLogFeed } from '@/console/hooks/useLiveLogFeed'
import { filterLogs } from '@/console/lib/logsLogic'
import LogHeader from '@/console/zones/logs/LogHeader'
import LogStatStrip from '@/console/zones/logs/LogStatStrip'
import LiveLogConsole from '@/console/zones/logs/LiveLogConsole'
import VramPanel from '@/console/zones/logs/VramPanel'

export default function LogsPage() {
  const [paused, setPaused] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [query, setQuery] = useState('')
  const [levels, setLevels] = useState<Set<LogLevel>>(new Set())
  const [sources, setSources] = useState<Set<LogSource>>(new Set())

  const { logs, clear } = useLiveLogFeed(paused)

  const filtered = useMemo(
    () => filterLogs(logs, { levels, sources, query }),
    [logs, levels, sources, query],
  )

  const toggleLevel = useCallback((l: LogLevel) => {
    setLevels((prev) => { const n = new Set(prev); if (n.has(l)) n.delete(l); else n.add(l); return n })
  }, [])
  const toggleSource = useCallback((s: LogSource) => {
    setSources((prev) => { const n = new Set(prev); if (n.has(s)) n.delete(s); else n.add(s); return n })
  }, [])

  return (
    <div className="h-full flex flex-col rounded-xl overflow-hidden bg-[#111827]/90 border border-white/5">
      <LogHeader
        count={filtered.length}
        paused={paused}
        autoScroll={autoScroll}
        query={query}
        activeLevels={levels}
        activeSources={sources}
        onTogglePause={() => setPaused((x) => !x)}
        onToggleAutoScroll={() => setAutoScroll((a) => !a)}
        onClear={clear}
        onQuery={setQuery}
        onToggleLevel={toggleLevel}
        onToggleSource={toggleSource}
      />
      <VramPanel />
      <LogStatStrip logs={logs} now={Date.now()} />
      <LiveLogConsole logs={filtered} autoScroll={autoScroll} />
    </div>
  )
}
