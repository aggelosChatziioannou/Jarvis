import { Mic, Speaker, Radio, Volume2, MicOff } from 'lucide-react'
import { useAssistantAudioCtx } from '@/console/services/AssistantAudioContext'
import type { AudioDevice } from '@/lib/api'

function DeviceSelect({
  icon: Icon,
  label,
  devices,
  value,
  optionValue,
  onPick,
  accent,
  placeholder,
}: {
  icon: typeof Mic
  label: string
  devices: AudioDevice[]
  value: string
  optionValue: (d: AudioDevice) => string
  onPick: (d: AudioDevice) => void
  accent: string
  placeholder: string
}) {
  return (
    <div className="rounded-xl p-3 mb-3" style={{ backgroundColor: 'rgba(17,24,39,0.7)', border: '1px solid rgba(255,255,255,0.05)' }}>
      <div className="flex items-center gap-2 mb-2">
        <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${accent}15`, border: `1px solid ${accent}20` }}>
          <span style={{ color: accent }}><Icon size={14} /></span>
        </div>
        <div className="text-[9px] text-[#475569] tracking-wider uppercase font-medium">{label}</div>
      </div>
      <select
        value={value}
        onChange={(e) => {
          const d = devices.find((x) => optionValue(x) === e.target.value)
          if (d) onPick(d)
        }}
        className="w-full h-8 px-3 rounded-lg text-[12px] text-[#f8fafc] border border-white/5 outline-none cursor-pointer appearance-none focus:border-[#22d3ee]/30"
        style={{ backgroundColor: 'rgba(10,14,23,0.8)' }}
      >
        <option value="">{placeholder}</option>
        {devices.map((d) => (
          <option key={optionValue(d)} value={optionValue(d)}>
            {d.name}
            {d.is_default ? ' (default)' : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

export default function DeviceControls() {
  const { connected, state, inputs, outputs, selectedInput, selectedOutput, setInput, setOutput, testTone, toggleMute, saved } =
    useAssistantAudioCtx()
  const muted = state?.isMuted ?? false

  return (
    <div className="rounded-xl p-4" style={{ backgroundColor: 'rgba(17,24,39,0.5)', border: '1px solid rgba(255,255,255,0.05)' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Radio size={13} className="text-[#22d3ee]" />
          <span className="text-[11px] text-[#94a3b8] tracking-wider uppercase font-medium">Assistant Devices</span>
        </div>
        <span
          className="text-[9px] font-mono-data px-1.5 py-0.5 rounded-full"
          style={{ color: connected ? '#34d399' : '#475569', background: connected ? '#34d3991a' : '#47556922' }}
        >
          {connected ? 'Connected' : 'Offline'}
        </span>
      </div>

      <DeviceSelect
        icon={Mic}
        label="Input (wake mic)"
        devices={inputs}
        value={selectedInput}
        optionValue={(d) => d.name}
        onPick={(d) => void setInput(d)}
        accent="#22d3ee"
        placeholder="System default"
      />
      <DeviceSelect
        icon={Speaker}
        label="Output (TTS)"
        devices={outputs}
        value={selectedOutput}
        optionValue={(d) => d.name}
        onPick={(d) => void setOutput(d)}
        accent="#a78bfa"
        placeholder="System default"
      />

      <div className="flex items-center gap-2 mt-2">
        <button
          onClick={toggleMute}
          disabled={!connected}
          title={muted ? 'Unmute the assistant mic' : 'Mute the assistant mic'}
          className="flex-1 h-8 rounded-lg text-[11px] font-medium flex items-center justify-center gap-1.5 disabled:opacity-40"
          style={
            muted
              ? { background: 'rgba(239,68,68,0.12)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.25)' }
              : { background: 'rgba(34,211,238,0.08)', color: '#22d3ee', border: '1px solid rgba(34,211,238,0.15)' }
          }
        >
          {muted ? <MicOff size={12} /> : <Mic size={12} />} {muted ? 'Muted' : 'Mute'}
        </button>
        <button
          onClick={testTone}
          disabled={!connected}
          title="Play a test tone on the assistant's output device"
          className="h-8 px-3 rounded-lg text-[11px] font-medium text-[#a78bfa] flex items-center gap-1.5 disabled:opacity-40"
          style={{ background: 'rgba(167,139,250,0.08)', border: '1px solid rgba(167,139,250,0.15)' }}
        >
          <Volume2 size={12} /> Tone
        </button>
      </div>

      {saved && (
        <div className="mt-2 text-[10px] text-[#fbbf24] flex items-center gap-1">
          ⚠ Saved. Restart Jarvis to apply device changes.
        </div>
      )}
    </div>
  )
}
