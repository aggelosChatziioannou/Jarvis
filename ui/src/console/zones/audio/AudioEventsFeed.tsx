import { useEffect, useRef } from 'react'
import { Activity, Trash2 } from 'lucide-react'
import { useAudioEngineCtx } from '@/console/context/AudioEngineContext'
import { EVENT_COLORS } from '@/console/types/audio'

function fmt(ts: number): string {
  const d = new Date(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export default function AudioEventsFeed() {
  const { events, clearEvents } = useAudioEngineCtx()
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [events])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 mb-3 px-1">
        <Activity size={13} className="text-[#22d3ee]" />
        <span className="text-[11px] text-[#94a3b8] tracking-wider uppercase font-medium">Audio Events</span>
        <span className="ml-auto text-[10px] text-[#475569] font-mono">{events.length}</span>
        <button onClick={clearEvents} title="Clear" className="p-1 rounded text-[#475569] hover:text-[#94a3b8]"><Trash2 size={12} /></button>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto pr-1 space-y-1">
        {events.length === 0 ? (
          <div className="h-full flex items-center justify-center text-[#475569] text-[11px]">No events yet. Enable the mic or play a test tone.</div>
        ) : events.map((e) => {
          const color = EVENT_COLORS[e.level]
          return (
            <div key={e.id} className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg border-l-2 hover:bg-white/[0.03] transition-colors"
                 style={{ borderColor: color }}>
              <span className="text-[10px] font-mono text-[#475569] shrink-0">{fmt(e.ts)}</span>
              <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: color }} />
              <span className="text-[9px] font-mono uppercase shrink-0" style={{ color }}>{e.type}</span>
              <span className="text-[11px] text-[#cbd5e1] truncate">{e.message}</span>
            </div>
          )
        })}
      </div>
      <div className="mt-2 pt-2 border-t border-white/5 flex items-center justify-between px-1">
        <div className="flex items-center gap-1.5">
          <div className="w-1 h-1 rounded-full bg-[#22d3ee] animate-glow-pulse" />
          <span className="text-[9px] text-[#475569] font-mono tracking-wider">LIVE</span>
        </div>
        <span className="text-[9px] text-[#475569] font-mono">audio telemetry</span>
      </div>
    </div>
  )
}
