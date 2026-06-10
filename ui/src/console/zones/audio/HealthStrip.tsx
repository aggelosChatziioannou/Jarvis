import { useEffect, useState } from 'react'
import { Activity, Ear, Sparkles, Radio } from 'lucide-react'
import { useAudioEngineCtx } from '@/console/context/AudioEngineContext'

// Real telemetry cards. Everything shown here is measured: input level from
// the active signal source, VAD + wake score + state from the daemon's
// listener via /ws/audio. No derived/fake percentages.
export default function HealthStrip() {
  const { daemon, levelRef } = useAudioEngineCtx()
  const [db, setDb] = useState(-60)

  useEffect(() => {
    const iv = window.setInterval(() => {
      setDb(Math.round(levelRef.current.db))
    }, 200)
    return () => window.clearInterval(iv)
  }, [levelRef])

  const dbPct = Math.max(0, Math.min(100, ((db + 60) / 60) * 100))
  const wakePct = daemon.wake != null ? Math.round(daemon.wake * 100) : null
  const vadPct = daemon.vad != null ? Math.round(daemon.vad * 100) : null

  const items = [
    {
      icon: <Activity size={13} />, label: 'Input level', color: '#34d399',
      value: db <= -60 ? 'silent' : `${db} dB`, pct: dbPct,
    },
    {
      icon: <Ear size={13} />, label: 'Voice (VAD)', color: '#22d3ee',
      value: daemon.connected ? (daemon.voiced ? 'speaking' : vadPct != null ? `${vadPct}%` : 'quiet') : '—',
      pct: daemon.voiced ? 100 : vadPct ?? 0,
    },
    {
      icon: <Sparkles size={13} />, label: 'Wake score', color: '#a78bfa',
      value: wakePct != null ? `${wakePct}%` : '—', pct: wakePct ?? 0,
    },
    {
      icon: <Radio size={13} />, label: 'Listener', color: daemon.connected ? '#fbbf24' : '#475569',
      value: daemon.connected ? daemon.state : 'offline', pct: daemon.connected ? 100 : 0,
    },
  ]
  return (
    <div className="flex gap-2">
      {items.map((it) => (
        <div key={it.label} className="flex-1 min-w-0 rounded-xl p-2.5 flex items-center gap-2"
             style={{ backgroundColor: 'rgba(17,24,39,0.6)', border: '1px solid rgba(255,255,255,0.04)' }}>
          <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: `${it.color}12`, border: `1px solid ${it.color}20` }}>
            <span style={{ color: it.color }}>{it.icon}</span>
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[9px] text-[#475569] tracking-wider uppercase truncate">{it.label}</div>
            <div className="text-[12px] font-semibold truncate" style={{ color: it.color }}>{it.value}</div>
            <div className="w-full h-0.5 rounded-full mt-1 overflow-hidden" style={{ backgroundColor: 'rgba(255,255,255,0.03)' }}>
              <div className="h-full rounded-full transition-all duration-300" style={{ width: `${it.pct}%`, backgroundColor: it.color }} />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
