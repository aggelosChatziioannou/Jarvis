import { Cpu, MemoryStick, Gauge, Clock, BrainCircuit, Music, Mail, Calendar, Cloud, Bell } from 'lucide-react'
import { useDashboardDataCtx } from '@/console/services/DashboardDataContext'

function fmtUptime(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function gb(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}

const SERVICE_ICON: Record<string, typeof Music> = {
  reminders: Bell,
  weather: Cloud,
  spotify: Music,
  gmail: Mail,
  calendar: Calendar,
}

export default function SystemStatusPanel() {
  const { metrics, services, connected } = useDashboardDataCtx()

  const rows: { label: string; value: string; icon: typeof Cpu }[] = []
  if (metrics) {
    if (metrics.cpu_percent != null) rows.push({ label: 'Processor', value: `${Math.round(metrics.cpu_percent)}%`, icon: Cpu })
    if (metrics.ram) rows.push({ label: 'Memory', value: `${Math.round(metrics.ram.percent)}%`, icon: MemoryStick })
    if (metrics.gpu) rows.push({ label: 'GPU / VRAM', value: `${metrics.gpu.util_percent}% · ${gb(metrics.gpu.mem_used_mb * 1024 ** 2)}`, icon: Gauge })
    rows.push({ label: 'Uptime', value: fmtUptime(metrics.uptime_sec), icon: Clock })
    if (metrics.models.length) rows.push({ label: 'Model', value: metrics.models[0], icon: BrainCircuit })
    if (metrics.weather?.temp_c != null) rows.push({ label: 'Weather', value: `${Math.round(metrics.weather.temp_c)}°C ${metrics.weather.description}`, icon: Cloud })
  }

  return (
    <div
      className="absolute right-6 top-1/2 z-40 hidden lg:block -translate-y-1/2"
      style={{
        width: '280px',
        background: 'rgba(17, 24, 39, 0.95)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(34, 211, 238, 0.15)',
        borderRadius: '12px',
        padding: '24px',
      }}
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-clash text-sm font-semibold uppercase tracking-wider" style={{ color: '#f8fafc', letterSpacing: '0.06em' }}>
          System Status
        </h3>
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: connected ? '#34d399' : '#475569' }}
          title={connected ? 'Connected' : 'Offline'}
        />
      </div>

      {/* Metrics */}
      <div className="space-y-3 mb-6">
        {rows.length === 0 && (
          <div className="text-xs" style={{ color: '#475569' }}>
            {connected ? 'Reading metrics…' : 'Daemon offline'}
          </div>
        )}
        {rows.map((m) => (
          <div key={m.label} className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-semibold flex items-center gap-1.5" style={{ color: '#94a3b8', letterSpacing: '0.06em' }}>
              <m.icon size={12} /> {m.label}
            </span>
            <span className="font-mono-data text-sm font-medium" style={{ color: '#f8fafc' }}>
              {m.value}
            </span>
          </div>
        ))}
      </div>

      <div className="h-px w-full mb-4" style={{ background: 'rgba(34, 211, 238, 0.1)' }} />

      {/* Active Services */}
      <h4 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: '#94a3b8', letterSpacing: '0.06em' }}>
        Services
      </h4>
      <div className="space-y-2">
        {services.map((s) => {
          const Icon = SERVICE_ICON[s.id] ?? Cloud
          const color = s.connected ? '#22d3ee' : '#475569'
          return (
            <div key={s.id} className="flex items-center gap-3 rounded-lg px-2 py-2">
              <div className="flex items-center justify-center w-8 h-8 rounded-md" style={{ background: `${color}15` }}>
                <Icon size={16} style={{ color }} />
              </div>
              <div className="flex-1">
                <div className="text-sm font-medium" style={{ color: '#f8fafc' }}>{s.name}</div>
                <div className="text-xs" style={{ color: '#94a3b8' }}>{s.detail}</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
