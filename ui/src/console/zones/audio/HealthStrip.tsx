import { Shield, VolumeX, Ear, Zap } from 'lucide-react'
import { useAudioEngineCtx } from '@/console/context/AudioEngineContext'

export default function HealthStrip() {
  const { health } = useAudioEngineCtx()
  const items = [
    { icon: <Shield size={13} />, label: 'Quality', value: `${health.quality}%`, color: '#34d399', pct: health.quality },
    { icon: <VolumeX size={13} />, label: 'Noise', value: `${health.noise}%`, color: '#22d3ee', pct: health.noise },
    { icon: <Ear size={13} />, label: 'Clarity', value: `${health.clarity}%`, color: '#a78bfa', pct: health.clarity },
    { icon: <Zap size={13} />, label: 'Response', value: `${health.responseMs}ms`, color: '#fbbf24', pct: Math.min(100, Math.max(8, 100 - health.responseMs)) },
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
