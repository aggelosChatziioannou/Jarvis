import { Mic, Speaker, Radio, Volume2, Zap } from 'lucide-react'
import { useAudioEngineCtx } from '@/console/context/AudioEngineContext'
import type { AudioDevice, PermissionState } from '@/console/types/audio'

function DeviceSelect({ icon: Icon, label, devices, value, onChange, accent, placeholder }: {
  icon: typeof Mic; label: string; devices: AudioDevice[]; value: string; onChange: (id: string) => void; accent: string; placeholder: string
}) {
  return (
    <div className="rounded-xl p-3 mb-3" style={{ backgroundColor: 'rgba(17,24,39,0.7)', border: '1px solid rgba(255,255,255,0.05)' }}>
      <div className="flex items-center gap-2 mb-2">
        <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${accent}15`, border: `1px solid ${accent}20` }}>
          <span style={{ color: accent }}><Icon size={14} /></span>
        </div>
        <div className="text-[9px] text-[#475569] tracking-wider uppercase font-medium">{label}</div>
      </div>
      <select value={value} onChange={(e) => onChange(e.target.value)}
              className="w-full h-8 px-3 rounded-lg text-[12px] text-[#f8fafc] border border-white/5 outline-none cursor-pointer appearance-none focus:border-[#22d3ee]/30"
              style={{ backgroundColor: 'rgba(10,14,23,0.8)' }}>
        {devices.length === 0 && <option value="">{placeholder}</option>}
        {devices.map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label}</option>)}
      </select>
    </div>
  )
}

const PERM_LABEL: Record<PermissionState, { text: string; color: string }> = {
  idle: { text: 'Demo', color: '#475569' },
  granted: { text: 'Live', color: '#34d399' },
  denied: { text: 'Denied', color: '#ef4444' },
  unsupported: { text: 'Unsupported', color: '#fbbf24' },
}

export default function DeviceControls() {
  const { inputDevices, outputDevices, selectedInput, selectedOutput, selectInput, selectOutput,
    mode, setMode, permission, testMic, playTestTone } = useAudioEngineCtx()
  const pill = PERM_LABEL[permission]

  return (
    <div className="rounded-xl p-4" style={{ backgroundColor: 'rgba(17,24,39,0.5)', border: '1px solid rgba(255,255,255,0.05)' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Radio size={13} className="text-[#22d3ee]" />
          <span className="text-[11px] text-[#94a3b8] tracking-wider uppercase font-medium">Devices</span>
        </div>
        <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-full" style={{ color: pill.color, background: `${pill.color}1a` }}>{pill.text}</span>
      </div>

      <DeviceSelect icon={Mic} label="Input" devices={inputDevices} value={selectedInput} onChange={(id) => void selectInput(id)} accent="#22d3ee" placeholder="Default Microphone" />
      <DeviceSelect icon={Speaker} label="Output" devices={outputDevices} value={selectedOutput} onChange={(id) => void selectOutput(id)} accent="#a78bfa" placeholder="System Default" />

      <div className="flex items-center gap-2 mt-2">
        <div className="flex rounded-lg overflow-hidden border border-white/5">
          {(['demo', 'live'] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)}
                    className="px-3 py-1.5 text-[11px] font-semibold transition-colors"
                    style={{ background: mode === m ? '#22d3ee' : 'transparent', color: mode === m ? '#0a0e17' : '#475569' }}>
              {m === 'live' ? 'Live' : 'Demo'}
            </button>
          ))}
        </div>
        <button onClick={testMic} title="Test microphone"
                className="flex-1 h-8 rounded-lg text-[11px] font-medium text-[#22d3ee] flex items-center justify-center gap-1.5"
                style={{ background: 'rgba(34,211,238,0.08)', border: '1px solid rgba(34,211,238,0.15)' }}>
          <Zap size={12} /> Test mic
        </button>
        <button onClick={playTestTone} title="Play test tone"
                className="h-8 px-3 rounded-lg text-[11px] font-medium text-[#a78bfa] flex items-center gap-1.5"
                style={{ background: 'rgba(167,139,250,0.08)', border: '1px solid rgba(167,139,250,0.15)' }}>
          <Volume2 size={12} /> Tone
        </button>
      </div>
    </div>
  )
}
