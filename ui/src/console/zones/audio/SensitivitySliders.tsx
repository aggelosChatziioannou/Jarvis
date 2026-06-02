import { Volume2 } from 'lucide-react'
import { useAudioEngineCtx } from '@/console/context/AudioEngineContext'
import type { EngineParams } from '@/console/types/audio'

function Slider({ label, value, onChange, color, suffix }: { label: string; value: number; onChange: (v: number) => void; color: string; suffix?: string }) {
  return (
    <div className="mb-4">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] text-[#94a3b8] tracking-wide">{label}</span>
        <span className="text-[10px] font-mono text-[#475569]">{value}{suffix}</span>
      </div>
      <div className="relative h-5 flex items-center">
        <div className="absolute inset-x-0 h-1 rounded-full overflow-hidden" style={{ backgroundColor: 'rgba(255,255,255,0.03)' }}>
          <div className="h-full rounded-full" style={{ width: `${value}%`, backgroundColor: color, boxShadow: `0 0 8px ${color}40` }} />
        </div>
        <input type="range" min={0} max={100} value={value}
               onChange={(e) => onChange(Number(e.target.value))}
               className="absolute inset-x-0 w-full h-5 opacity-0 cursor-pointer" />
      </div>
    </div>
  )
}

const SLIDERS: { key: keyof EngineParams; label: string; color: string; suffix?: string }[] = [
  { key: 'detection', label: 'Detection Strength', color: '#22d3ee', suffix: '%' },
  { key: 'outputVolume', label: 'Output Volume', color: '#a78bfa', suffix: '%' },
  { key: 'noiseFloor', label: 'Noise Floor', color: '#fbbf24', suffix: '%' },
  { key: 'smoothing', label: 'Smoothing', color: '#34d399', suffix: '%' },
]

export default function SensitivitySliders() {
  const { params, setParam } = useAudioEngineCtx()
  return (
    <div className="rounded-xl p-4" style={{ backgroundColor: 'rgba(17,24,39,0.7)', border: '1px solid rgba(255,255,255,0.05)' }}>
      <div className="flex items-center gap-2 mb-3">
        <Volume2 size={13} className="text-[#22d3ee]" />
        <span className="text-[11px] text-[#94a3b8] tracking-wider uppercase font-medium">Sensitivity</span>
      </div>
      {SLIDERS.map((s) => (
        <Slider key={s.key} label={s.label} value={params[s.key]} color={s.color} suffix={s.suffix}
                onChange={(v) => setParam(s.key, v)} />
      ))}
    </div>
  )
}
