import { useEffect, useState } from 'react'
import { useSceneContext } from '@/console/3d/SceneContext'
import { useDashboardDataCtx } from '@/console/services/DashboardDataContext'
import { fetchReminders } from '@/console/services/dashboardApi'
import type { ReminderItem } from '@/console/services/dashboardApi'
import { X, Cpu, CloudSun, Mail, CalendarDays, BellRing, BrainCircuit } from 'lucide-react'
import type { PanelId } from '@/console/3d/furnitureActions'

// Generic glass panel for furniture-triggered info views. All data is real:
// system metrics + service status come from DashboardDataContext (5s poll),
// reminders are fetched on open. 'nowplaying' is handled by NowPlayingPanel.
const TITLES: Partial<Record<PanelId, { title: string; icon: typeof Cpu }>> = {
  system: { title: 'System Status', icon: Cpu },
  weather: { title: 'Weather', icon: CloudSun },
  gmail: { title: 'Gmail', icon: Mail },
  calendar: { title: 'Calendar', icon: CalendarDays },
  reminders: { title: 'Reminders', icon: BellRing },
  model: { title: 'AI Core', icon: BrainCircuit },
}

function fmtUptime(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-xs" style={{ color: '#94a3b8' }}>{label}</span>
      <span className="text-xs font-medium text-right" style={{ color: '#f8fafc' }}>{value}</span>
    </div>
  )
}

export default function InfoPanel() {
  const { openPanel, setOpenPanel } = useSceneContext()
  const { metrics, services, state } = useDashboardDataCtx()
  const [reminders, setReminders] = useState<ReminderItem[] | null>(null)

  useEffect(() => {
    if (openPanel === 'reminders') {
      setReminders(null)
      void fetchReminders().then(setReminders)
    }
  }, [openPanel])

  if (!openPanel || openPanel === 'nowplaying') return null
  const meta = TITLES[openPanel]
  if (!meta) return null
  const Icon = meta.icon

  const svc = (id: string) => services.find((s) => s.id === id)

  let body: React.ReactNode = null
  if (openPanel === 'system') {
    body = metrics ? (
      <>
        <Row label="Processor" value={metrics.cpu_percent != null ? `${Math.round(metrics.cpu_percent)}%` : '—'} />
        <Row
          label="Memory"
          value={metrics.ram ? `${Math.round(metrics.ram.percent)}% · ${(metrics.ram.used / 1e9).toFixed(1)} / ${(metrics.ram.total / 1e9).toFixed(0)} GB` : '—'}
        />
        <Row
          label="GPU / VRAM"
          value={metrics.gpu ? `${metrics.gpu.util_percent}% · ${(metrics.gpu.mem_used_mb / 1024).toFixed(1)} / ${(metrics.gpu.mem_total_mb / 1024).toFixed(0)} GB` : '—'}
        />
        <Row label="Uptime" value={fmtUptime(metrics.uptime_sec)} />
      </>
    ) : (
      <div className="text-xs" style={{ color: '#475569' }}>Waiting for metrics…</div>
    )
  } else if (openPanel === 'weather') {
    const w = metrics?.weather
    body = w ? (
      <>
        <Row label="Now" value={`${w.temp_c != null ? `${Math.round(w.temp_c)}°C` : '—'} ${w.description}`} />
        <Row label="Location" value={w.place || '—'} />
      </>
    ) : (
      <div className="text-xs" style={{ color: '#475569' }}>Weather unavailable</div>
    )
  } else if (openPanel === 'gmail') {
    const g = svc('gmail')
    body = g?.connected ? (
      <>
        <Row label="Unread" value={g.count != null ? String(g.count) : '—'} />
        <Row label="Status" value={g.detail || 'connected'} />
      </>
    ) : (
      <div className="text-xs" style={{ color: '#475569' }}>Gmail not connected</div>
    )
  } else if (openPanel === 'calendar') {
    const c = svc('calendar')
    body = c?.connected ? (
      <Row label="Status" value={c.detail || 'connected'} />
    ) : (
      <div className="text-xs" style={{ color: '#475569' }}>{c?.detail || 'Calendar not configured'}</div>
    )
  } else if (openPanel === 'model') {
    body = (
      <>
        <Row label="Model" value={metrics?.models?.length ? metrics.models.join(', ') : '—'} />
        <Row label="State" value={state?.state ?? '—'} />
        <Row label="Uptime" value={metrics ? fmtUptime(metrics.uptime_sec) : '—'} />
      </>
    )
  } else if (openPanel === 'reminders') {
    const pending = (reminders ?? []).filter((r) => r.status === 'pending')
    body = reminders === null ? (
      <div className="text-xs" style={{ color: '#475569' }}>Loading…</div>
    ) : pending.length === 0 ? (
      <div className="text-xs" style={{ color: '#475569' }}>No pending reminders</div>
    ) : (
      <div className="max-h-44 overflow-y-auto pr-1">
        {pending.slice(0, 8).map((r) => (
          <Row
            key={r.id}
            label={r.trigger_at ? new Date(r.trigger_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
            value={r.text}
          />
        ))}
        {pending.length > 8 && (
          <div className="text-[10px] mt-1" style={{ color: '#475569' }}>+{pending.length - 8} more in Memory → Timeline</div>
        )}
      </div>
    )
  }

  return (
    <div
      className="absolute left-1/2 bottom-6 z-50 -translate-x-1/2"
      style={{
        width: 360,
        maxWidth: 'calc(100vw - 48px)',
        background: 'rgba(17, 24, 39, 0.95)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(34, 211, 238, 0.15)',
        borderRadius: 12,
        padding: 16,
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider" style={{ color: '#94a3b8', letterSpacing: '0.06em' }}>
          <Icon size={14} style={{ color: '#22d3ee' }} />
          {meta.title}
        </h3>
        <button title="Close" onClick={() => setOpenPanel(null)} style={{ color: '#94a3b8' }}>
          <X size={16} />
        </button>
      </div>
      {body}
    </div>
  )
}
