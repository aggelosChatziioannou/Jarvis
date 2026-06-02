import { useEffect, useRef, useState } from 'react'
import { SlidersHorizontal, RotateCcw, Save } from 'lucide-react'
import { useAssistantAudioCtx } from '@/console/services/AssistantAudioContext'
import { SENSITIVITY_FIELDS } from '@/console/lib/audioConfig'

function fmt(value: number, step: number, unit?: string): string {
  const s = step < 1 ? value.toFixed(2) : String(Math.round(value))
  return unit ? `${s}${unit}` : s
}

function Slider({
  label,
  hint,
  value,
  min,
  max,
  step,
  unit,
  onChange,
}: {
  label: string
  hint: string
  value: number
  min: number
  max: number
  step: number
  unit?: string
  onChange: (v: number) => void
}) {
  const pct = ((value - min) / (max - min)) * 100
  return (
    <div className="mb-4">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] text-[#94a3b8] tracking-wide">{label}</span>
        <span className="text-[10px] font-mono-data text-[#22d3ee]">{fmt(value, step, unit)}</span>
      </div>
      <div className="relative h-5 flex items-center">
        <div className="absolute inset-x-0 h-1 rounded-full overflow-hidden" style={{ backgroundColor: 'rgba(255,255,255,0.03)' }}>
          <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: '#22d3ee', boxShadow: '0 0 8px #22d3ee40' }} />
        </div>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="absolute inset-x-0 w-full h-5 opacity-0 cursor-pointer"
        />
      </div>
      <div className="text-[9px] text-[#475569] mt-0.5 leading-tight">{hint}</div>
    </div>
  )
}

export default function SensitivitySliders() {
  const { sensitivity, saveSensitivity, connected } = useAssistantAudioCtx()
  const baseline = JSON.stringify(sensitivity)
  const [local, setLocal] = useState<Record<string, number>>(sensitivity)
  const lastBaseline = useRef(baseline)

  // Re-sync local edits whenever the SAVED config changes (initial load / after save),
  // without clobbering in-progress edits on every render.
  useEffect(() => {
    if (lastBaseline.current !== baseline) {
      lastBaseline.current = baseline
      setLocal(sensitivity)
    }
  }, [baseline, sensitivity])

  const dirty = JSON.stringify(local) !== baseline

  return (
    <div className="rounded-xl p-4" style={{ backgroundColor: 'rgba(17,24,39,0.7)', border: '1px solid rgba(255,255,255,0.05)' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <SlidersHorizontal size={13} className="text-[#22d3ee]" />
          <span className="text-[11px] text-[#94a3b8] tracking-wider uppercase font-medium">Listening Sensitivity</span>
        </div>
        <span className="text-[9px] text-[#475569]">applies after restart</span>
      </div>

      {SENSITIVITY_FIELDS.map((f) => (
        <Slider
          key={f.key}
          label={f.label}
          hint={f.hint}
          value={local[f.key] ?? f.default}
          min={f.min}
          max={f.max}
          step={f.step}
          unit={f.unit}
          onChange={(v) => setLocal((prev) => ({ ...prev, [f.key]: v }))}
        />
      ))}

      <div className="flex items-center gap-2 mt-1">
        <button
          onClick={() => setLocal(Object.fromEntries(SENSITIVITY_FIELDS.map((f) => [f.key, f.default])))}
          className="h-8 px-3 rounded-lg text-[11px] font-medium text-[#94a3b8] flex items-center gap-1.5"
          style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          <RotateCcw size={12} /> Defaults
        </button>
        <button
          onClick={() => void saveSensitivity(local)}
          disabled={!dirty || !connected}
          className="flex-1 h-8 rounded-lg text-[11px] font-semibold flex items-center justify-center gap-1.5 disabled:opacity-40"
          style={{ background: 'rgba(34,211,238,0.12)', color: '#22d3ee', border: '1px solid rgba(34,211,238,0.3)' }}
        >
          <Save size={12} /> {dirty ? 'Save changes' : 'Saved'}
        </button>
      </div>
    </div>
  )
}
