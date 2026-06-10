import { useEffect, useMemo, useState } from 'react'
import { Save, RotateCcw, Server } from 'lucide-react'
import { api } from '@/lib/api'
import type { MCPInfo } from '@/lib/api'
import { SETTINGS_FIELDS, coerce, settingsDiff } from '@/console/lib/settingsSchema'
import type { SettingsField } from '@/console/lib/settingsSchema'

type Val = string | number | boolean

function buildState(config: Record<string, unknown>): Record<string, Val> {
  const out: Record<string, Val> = {}
  for (const f of SETTINGS_FIELDS) out[f.key] = coerce(config[f.key], f.type)
  return out
}

function Field({ field, value, models, onChange }: {
  field: SettingsField
  value: Val
  models: string[]
  onChange: (v: Val) => void
}) {
  const labelEl = (
    <div className="flex items-center justify-between mb-1">
      <span className="text-[12px] text-[#94a3b8]">{field.label}</span>
      {field.hint && <span className="text-[9px] text-[#475569]">{field.hint}</span>}
    </div>
  )
  const inputCls =
    'w-full h-8 px-3 rounded-lg text-[12px] text-[#f8fafc] bg-[#0a0e17] border border-white/5 outline-none focus:border-[#22d3ee]/40'

  if (field.type === 'toggle') {
    return (
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[12px] text-[#94a3b8]">{field.label}</span>
        <button
          onClick={() => onChange(!(value as boolean))}
          className="w-10 h-5 rounded-full transition-colors relative"
          style={{ background: value ? '#22d3ee' : 'rgba(255,255,255,0.08)' }}
        >
          <span
            className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all"
            style={{ left: value ? '22px' : '2px' }}
          />
        </button>
      </div>
    )
  }

  if (field.type === 'select') {
    const opts = field.dynamicOptions === 'models' ? models : field.options ?? []
    return (
      <div className="mb-3">
        {labelEl}
        <select value={String(value)} onChange={(e) => onChange(e.target.value)} className={`${inputCls} cursor-pointer appearance-none`}>
          {!opts.includes(String(value)) && <option value={String(value)}>{String(value) || '— none —'}</option>}
          {opts.map((o) => <option key={o} value={o}>{field.optionLabels?.[o] ?? o}</option>)}
        </select>
      </div>
    )
  }

  return (
    <div className="mb-3">
      {labelEl}
      <input
        type={field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text'}
        value={String(value)}
        onChange={(e) => onChange(coerce(e.target.value, field.type))}
        className={inputCls}
      />
    </div>
  )
}

export default function SettingsPage() {
  const [original, setOriginal] = useState<Record<string, Val>>({})
  const [edited, setEdited] = useState<Record<string, Val>>({})
  const [models, setModels] = useState<string[]>([])
  const [mcps, setMcps] = useState<MCPInfo[]>([])
  const [connected, setConnected] = useState(false)
  const [saved, setSaved] = useState(false)
  const [savedMsg, setSavedMsg] = useState('Saved · restart may be required')

  useEffect(() => {
    let alive = true
    api.getConfig().then((c) => {
      if (!alive) return
      const s = buildState(c)
      setOriginal(s)
      setEdited(s)
      setConnected(true)
    }).catch(() => {})
    api.llmModels().then((m) => { if (alive) setModels(m.map((x) => x.name)) }).catch(() => {})
    api.mcps().then((m) => { if (alive) setMcps(m) }).catch(() => {})
    return () => { alive = false }
  }, [])

  const diff = useMemo(() => settingsDiff(original, edited), [original, edited])
  const dirty = Object.keys(diff).length > 0

  const groups = useMemo(() => {
    const g = new Map<string, SettingsField[]>()
    for (const f of SETTINGS_FIELDS) {
      const list = g.get(f.group) ?? []
      list.push(f)
      g.set(f.group, list)
    }
    return Array.from(g.entries())
  }, [])

  const save = async () => {
    if (!dirty) return
    const switchingStt = 'stt_backend' in diff
    await api.patchConfig(diff)
    setOriginal({ ...edited })
    setSavedMsg(
      switchingStt
        ? 'Saved · switching STT backend… (watch Live Logs)'
        : 'Saved · restart may be required',
    )
    setSaved(true)
  }

  const toggleMcp = async (m: MCPInfo) => {
    await api.toggleMcp(m.id, !m.enabled)
    setMcps((prev) => prev.map((x) => (x.id === m.id ? { ...x, enabled: !x.enabled } : x)))
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-[640px] mx-auto py-2">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-sm font-semibold tracking-widest text-[#f8fafc] uppercase">Settings</h1>
          <div className="flex items-center gap-2">
            {saved && <span className="text-[10px] text-[#fbbf24]">{savedMsg}</span>}
            <span className="text-[9px] font-mono-data px-1.5 py-0.5 rounded-full" style={{ color: connected ? '#34d399' : '#475569', background: connected ? '#34d3991a' : '#47556922' }}>
              {connected ? 'Connected' : 'Offline'}
            </span>
          </div>
        </div>

        {groups.map(([group, fields]) => (
          <div key={group} className="mb-4 rounded-xl p-4" style={{ background: 'rgba(17,24,39,0.6)', border: '1px solid rgba(255,255,255,0.05)' }}>
            <h2 className="text-[11px] font-semibold tracking-wider text-[#22d3ee] uppercase mb-3">{group}</h2>
            {fields.map((f) => (
              <Field
                key={f.key}
                field={f}
                value={edited[f.key] ?? ''}
                models={models}
                onChange={(v) => setEdited((prev) => ({ ...prev, [f.key]: v }))}
              />
            ))}
          </div>
        ))}

        {/* Services / MCP */}
        <div className="mb-4 rounded-xl p-4" style={{ background: 'rgba(17,24,39,0.6)', border: '1px solid rgba(255,255,255,0.05)' }}>
          <h2 className="text-[11px] font-semibold tracking-wider text-[#22d3ee] uppercase mb-3 flex items-center gap-1.5">
            <Server size={12} /> Services (MCP)
          </h2>
          {mcps.length === 0 && <div className="text-[11px] text-[#475569]">No services reported.</div>}
          {mcps.map((m) => (
            <div key={m.id} className="flex items-center justify-between mb-2">
              <div>
                <div className="text-[12px] text-[#f8fafc]">{m.name}</div>
                <div className="text-[10px] text-[#475569]">{m.description}</div>
              </div>
              <button
                onClick={() => void toggleMcp(m)}
                className="w-10 h-5 rounded-full transition-colors relative shrink-0"
                style={{ background: m.enabled ? '#22d3ee' : 'rgba(255,255,255,0.08)' }}
              >
                <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all" style={{ left: m.enabled ? '22px' : '2px' }} />
              </button>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2 pb-4">
          <button
            onClick={() => setEdited({ ...original })}
            disabled={!dirty}
            className="h-9 px-4 rounded-lg text-[12px] font-medium text-[#94a3b8] flex items-center gap-1.5 disabled:opacity-40"
            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}
          >
            <RotateCcw size={13} /> Revert
          </button>
          <button
            onClick={() => void save()}
            disabled={!dirty}
            className="flex-1 h-9 rounded-lg text-[12px] font-semibold flex items-center justify-center gap-1.5 disabled:opacity-40"
            style={{ background: 'rgba(34,211,238,0.12)', color: '#22d3ee', border: '1px solid rgba(34,211,238,0.3)' }}
          >
            <Save size={13} /> {dirty ? `Save ${Object.keys(diff).length} change(s)` : 'Saved'}
          </button>
        </div>
      </div>
    </div>
  )
}
