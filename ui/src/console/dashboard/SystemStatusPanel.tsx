import { Music, Mail, Calendar, Cloud, ChevronRight } from 'lucide-react'

export default function SystemStatusPanel() {
  const metrics = [
    { label: 'Temperature', value: '22.5°C', icon: '🌡️' },
    { label: 'Humidity', value: '48% RH', icon: '💧' },
    { label: 'Energy', value: '1.2 kW', icon: '⚡' },
  ]

  const services = [
    { name: 'Spotify', status: 'Playing', icon: Music, color: '#4ade80' },
    { name: 'Gmail', status: '3 unread', icon: Mail, color: '#22d3ee' },
    { name: 'Calendar', status: '1 alert', icon: Calendar, color: '#fbbf24' },
    { name: 'Weather', status: 'Clear 24°', icon: Cloud, color: '#f8fafc' },
  ]

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
      <h3
        className="font-clash text-sm font-semibold uppercase tracking-wider mb-4"
        style={{ color: '#f8fafc', letterSpacing: '0.06em' }}
      >
        System Status
      </h3>

      {/* Metrics */}
      <div className="space-y-3 mb-6">
        {metrics.map((m) => (
          <div key={m.label} className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-semibold" style={{ color: '#94a3b8', letterSpacing: '0.06em' }}>
              {m.label}
            </span>
            <span className="font-mono-data text-lg font-medium" style={{ color: '#f8fafc' }}>
              {m.value}
            </span>
          </div>
        ))}
      </div>

      {/* Divider */}
      <div className="h-px w-full mb-4" style={{ background: 'rgba(34, 211, 238, 0.1)' }} />

      {/* Active Services */}
      <h4
        className="text-xs font-semibold uppercase tracking-wider mb-3"
        style={{ color: '#94a3b8', letterSpacing: '0.06em' }}
      >
        Active Services
      </h4>
      <div className="space-y-2">
        {services.map((s) => {
          const Icon = s.icon
          return (
            <div
              key={s.name}
              className="flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-[rgba(34,211,238,0.05)] cursor-pointer"
            >
              <div
                className="flex items-center justify-center w-8 h-8 rounded-md"
                style={{ background: `${s.color}15` }}
              >
                <Icon size={16} style={{ color: s.color }} />
              </div>
              <div className="flex-1">
                <div className="text-sm font-medium" style={{ color: '#f8fafc' }}>
                  {s.name}
                </div>
                <div className="text-xs" style={{ color: '#94a3b8' }}>
                  {s.status}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* View All */}
      <button className="flex items-center gap-1 mt-4 text-sm font-medium transition-colors hover:text-[#22d3ee]" style={{ color: '#22d3ee' }}>
        View All Rooms
        <ChevronRight size={14} />
      </button>
    </div>
  )
}
