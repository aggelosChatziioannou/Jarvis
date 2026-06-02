import { useConnection } from '@/console/services/useConnection'
import { statusDisplay } from '@/console/lib/statusMap'

function todayISO(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export default function StatusBar() {
  const { state, connected, version } = useConnection()
  const status = statusDisplay(state, connected)

  return (
    <div className="h-8 shrink-0 bg-[#070a10] border-t border-white/5 flex items-center px-4 text-[11px] font-medium select-none">
      <div className="flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: status.color }} />
        <span className="text-[#94a3b8]">{status.label}</span>
      </div>
      <div className="flex-1 flex items-center justify-center gap-2">
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: connected ? '#22d3ee' : '#475569' }}
        />
        <span className="text-[#94a3b8]">{connected ? 'Connected' : 'Disconnected'}</span>
        <span className="text-[#475569]">·</span>
        <span className="text-[#475569] font-mono-data">{version ? `v${version}` : '…'}</span>
      </div>
      <div className="flex items-center gap-3 text-[#475569] font-mono-data">
        {/* Temperature wired in Phase 4 (weather + system metrics) */}
        <span>—</span>
        <span>{todayISO()}</span>
      </div>
    </div>
  )
}
