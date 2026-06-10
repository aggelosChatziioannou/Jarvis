import { useState } from 'react'
import { useSceneContext } from '@/console/3d/SceneContext'
import type { SystemMood, SceneMode, ServiceStates } from '@/console/3d/dollhouseTypes'
import { ChevronDown, ChevronUp, FlaskConical, Home } from 'lucide-react'

const MOODS: { key: SystemMood; label: string; color: string }[] = [
  { key: 'idle', label: 'Idle', color: '#22d3ee' },
  { key: 'processing', label: 'Processing', color: '#22d3ee' },
  { key: 'busy', label: 'Busy', color: '#fbbf24' },
  { key: 'warning', label: 'Warning', color: '#ef4444' },
  { key: 'success', label: 'Success', color: '#34d399' },
]

const TIMES: { key: SceneMode; label: string }[] = [
  { key: 'morning', label: 'Morning' },
  { key: 'afternoon', label: 'Afternoon' },
  { key: 'evening', label: 'Evening' },
  { key: 'night', label: 'Night' },
  { key: 'focus', label: 'Focus' },
  { key: 'away', label: 'Away' },
]

const TOGGLES: { key: keyof ServiceStates; label: string }[] = [
  { key: 'spotify', label: 'Spotify ▶' },
  { key: 'gmailUnread', label: 'Gmail ✉' },
  { key: 'calendarAlert', label: 'Cal ⏰' },
  { key: 'weatherAlert', label: 'Weather ⚠' },
  { key: 'taskActive', label: 'Task ◎' },
  { key: 'processing', label: 'AI ⚡' },
]

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-2.5">
      <div className="mb-1 font-mono-data" style={{ fontSize: '9px', letterSpacing: '1.5px', color: '#64748b' }}>{title}</div>
      <div className="flex flex-wrap gap-1">{children}</div>
    </div>
  )
}

function Chip({ active, onClick, children, accent = '#22d3ee' }: { active: boolean; onClick: () => void; children: React.ReactNode; accent?: string }) {
  return (
    <button
      onClick={onClick}
      className="rounded-md px-2 py-1 font-mono-data transition-all duration-150 active:scale-95"
      style={{
        fontSize: '10px',
        background: active ? `${accent}22` : 'rgba(255,255,255,0.03)',
        color: active ? accent : '#94a3b8',
        border: `1px solid ${active ? `${accent}66` : 'rgba(255,255,255,0.06)'}`,
        boxShadow: active ? `0 0 10px ${accent}33` : 'none',
      }}
    >
      {children}
    </button>
  )
}

export default function StatePanel() {
  const { sceneMode, setSceneMode, mood, setMood, services, toggleService, setActiveTarget } = useSceneContext()
  // Default collapsed on short windows so the panel never buries the scene.
  const [open, setOpen] = useState(() => (typeof window === 'undefined' ? true : window.innerHeight >= 760))

  const isOn = (k: keyof ServiceStates) => {
    const v = services[k]
    return typeof v === 'boolean' ? v : v > 0
  }

  return (
    <div
      className="absolute bottom-6 left-6 z-30 w-[240px] rounded-xl"
      style={{ background: 'rgba(17,24,39,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(34,211,238,0.15)' }}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between rounded-t-xl px-3 py-2"
        style={{ borderBottom: open ? '1px solid rgba(255,255,255,0.05)' : 'none' }}
      >
        <span className="flex items-center gap-1.5 font-mono-data" style={{ fontSize: '10px', letterSpacing: '1px', color: '#22d3ee' }}>
          <FlaskConical size={12} /> AI STATES · TESTING
        </span>
        {open ? <ChevronDown size={14} color="#64748b" /> : <ChevronUp size={14} color="#64748b" />}
      </button>

      {open && (
        <div className="p-3">
          <Section title="SYSTEM MOOD">
            {MOODS.map((m) => (
              <Chip key={m.key} active={mood === m.key} accent={m.color} onClick={() => setMood(m.key)}>{m.label}</Chip>
            ))}
          </Section>
          <Section title="TIME OF DAY">
            {TIMES.map((t) => (
              <Chip key={t.key} active={sceneMode === t.key} onClick={() => setSceneMode(t.key)}>{t.label}</Chip>
            ))}
          </Section>
          <Section title="SERVICE GLOWS">
            {TOGGLES.map((t) => (
              <Chip key={t.key} active={isOn(t.key)} onClick={() => toggleService(t.key)}>{t.label}</Chip>
            ))}
          </Section>
          <div className="mt-2 flex items-center gap-1.5 font-mono-data" style={{ fontSize: '9px', color: '#475569' }}>
            <span>Κάνε κλικ σε αντικείμενα · κενό = </span>
            <button
              onClick={() => setActiveTarget(null)}
              className="flex items-center gap-1 rounded px-1.5 py-0.5"
              style={{ color: '#22d3ee', border: '1px solid rgba(34,211,238,0.25)' }}
            >
              <Home size={9} /> Atrium
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
