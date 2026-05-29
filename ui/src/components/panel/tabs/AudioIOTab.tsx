import { useEffect, useState } from 'react';
import { Volume2, Mic, Speaker } from 'lucide-react';
import { api, openStateStream, type AudioDevices, type AudioDevice } from '@/lib/api';
import { SaveBar } from './WakeWordTab';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

/**
 * Audio I/O. Device pickers are ENDPOINT-ID based: the stable Windows Core
 * Audio endpoint id is persisted (`audio_input_endpoint_id` /
 * `audio_output_endpoint_id`) with the friendly name kept for display and as a
 * fallback. The list is live (Core Audio) and refreshes on device add/remove;
 * a remembered device that is currently unplugged stays selected and is shown
 * as "(disconnected)". There is no "follow Windows default" option.
 */
export default function AudioIOTab() {
  const [devices, setDevices] = useState<AudioDevices>({ inputs: [], outputs: [] });
  const [inId, setInId] = useState<string>('');   // audio_input_endpoint_id
  const [inName, setInName] = useState<string>(''); // audio_input_name
  const [outId, setOutId] = useState<string>('');   // audio_output_endpoint_id
  const [outName, setOutName] = useState<string>(''); // audio_output_name
  const [vadLevel, setVadLevel] = useState(1);
  const [threshold, setThreshold] = useState(0.005);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // Live, adaptive device list. pycaw Core Audio is the source of truth and the
  // list reflects hot-plug, so we (a) re-fetch when the daemon signals a device
  // change over /ws/state (the `devices_changed` counter pushed by the Core
  // Audio watcher) and (b) re-poll on a gentle interval as a fail-open safety
  // net in case the watcher could not register.
  useEffect(() => {
    let alive = true;
    const refresh = () =>
      api.audioDevices().then((d) => { if (alive) setDevices(d); }).catch(() => {});
    refresh();
    const timer = window.setInterval(refresh, 4000);
    let lastSig: number | undefined;
    const stop = openStateStream((s) => {
      if (s.devices_changed !== undefined && s.devices_changed !== lastSig) {
        lastSig = s.devices_changed;
        refresh();
      }
    });
    api
      .getConfig()
      .then((cfg) => {
        if (!alive) return;
        setInId(cfg.audio_input_endpoint_id == null ? '' : String(cfg.audio_input_endpoint_id));
        setInName(cfg.audio_input_name == null ? '' : String(cfg.audio_input_name));
        setOutId(cfg.audio_output_endpoint_id == null ? '' : String(cfg.audio_output_endpoint_id));
        setOutName(cfg.audio_output_name == null ? '' : String(cfg.audio_output_name));
        setVadLevel(Number(cfg.vad_aggressiveness ?? 1));
        setThreshold(Number(cfg.voice_min_energy ?? 0.005));
      })
      .catch(() => {});
    return () => { alive = false; window.clearInterval(timer); stop(); };
  }, []);

  // Migration bridge: config v7 forwarded the legacy device *name* but left the
  // endpoint id blank. Once the live list arrives, adopt the id of the device
  // whose name matches the remembered name so the picker shows the right entry.
  useEffect(() => {
    if (inId === '' && inName) {
      const m = devices.inputs.find((d) => d.name === inName);
      if (m) setInId(m.id);
    }
    if (outId === '' && outName) {
      const m = devices.outputs.find((d) => d.name === outName);
      if (m) setOutId(m.id);
    }
  }, [devices, inId, inName, outId, outName]);

  const save = async () => {
    await api.patchConfig({
      audio_input_endpoint_id: inId,
      audio_input_name: inName,
      audio_output_endpoint_id: outId,
      audio_output_name: outName,
      vad_aggressiveness: vadLevel,
      voice_min_energy: threshold,
    });
    setDirty(false);
    setSavedAt(Date.now());
  };

  const playTone = () => api.testTone().catch(() => {});

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, maxWidth: 700 }}>
      <SectionCard icon={<Mic size={18} />} title="Input (Microphone)">
        <FormRow label="Microphone">
          <DeviceSelect
            value={inId}
            selectedName={inName}
            onChange={(id, name) => {
              setInId(id);
              setInName(name);
              setDirty(true);
            }}
            options={devices.inputs}
          />
        </FormRow>
        <p style={hintStyle}>Where Jarvis listens for "Hey Jarvis".</p>
      </SectionCard>

      <SectionCard icon={<Speaker size={18} />} title="Output (Speaker)">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <FormRow label="Speaker">
            <DeviceSelect
              value={outId}
              selectedName={outName}
              onChange={(id, name) => {
                setOutId(id);
                setOutName(name);
                setDirty(true);
              }}
              options={devices.outputs}
            />
          </FormRow>
          <p style={hintStyle}>Where Jarvis speaks. Save first, then test below.</p>
          <FormRow label="">
            <button onClick={playTone} style={testBtnStyle}>
              <Volume2 size={14} />
              Test Tone
            </button>
          </FormRow>
        </div>
      </SectionCard>

      <SectionCard icon={<Volume2 size={18} />} title="Microphone Sensitivity">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <SliderRow
            label="Detection strength"
            value={vadLevel}
            min={0}
            max={3}
            step={1}
            onChange={(v) => {
              setVadLevel(v);
              setDirty(true);
            }}
            displayValue={['Off', 'Low', 'Medium', 'High'][vadLevel]}
          />
          <SliderRow
            label="Noise floor"
            value={threshold}
            min={0.001}
            max={0.05}
            step={0.001}
            onChange={(v) => {
              setThreshold(v);
              setDirty(true);
            }}
            displayValue={threshold.toFixed(3)}
          />
        </div>
      </SectionCard>

      <SaveBar dirty={dirty} onSave={save} savedAt={savedAt} />
    </div>
  );
}

const NONE_DEVICE = '__none__';

/**
 * Themed device picker built on the shadcn/Radix Select so the open option
 * list uses the app's dark+cyan popover tokens instead of the grey native
 * dropdown. Selection is by stable endpoint id (the friendly name is shown).
 * A remembered device that is currently unplugged is not in the live list, so
 * it is rendered as a synthetic "(disconnected)" entry and stays selected.
 * Radix forbids an empty-string value, so "no selection" maps to NONE_DEVICE
 * (which has no matching item, so the placeholder shows).
 */
function DeviceSelect({
  value,
  selectedName,
  onChange,
  options,
}: {
  value: string;
  selectedName: string;
  onChange: (id: string, name: string) => void;
  options: AudioDevice[];
}) {
  const known = options.some((d) => d.id === value);
  return (
    <Select
      value={value === '' ? NONE_DEVICE : value}
      onValueChange={(v) => {
        if (v === NONE_DEVICE) {
          onChange('', '');
          return;
        }
        const dev = options.find((d) => d.id === v);
        onChange(v, dev ? dev.name : selectedName);
      }}
    >
      <SelectTrigger style={selectStyle} aria-label="device">
        <SelectValue placeholder="Select a device" />
      </SelectTrigger>
      <SelectContent>
        {options.map((d) => (
          <SelectItem key={d.id} value={d.id}>
            {d.name}
            {d.available ? '' : ' (disconnected)'}
          </SelectItem>
        ))}
        {value !== '' && !known && (
          <SelectItem value={value}>
            {(selectedName || 'Selected device') + ' (disconnected)'}
          </SelectItem>
        )}
      </SelectContent>
    </Select>
  );
}

const selectStyle: React.CSSProperties = {
  background: 'rgba(8, 14, 28, 0.6)',
  border: '1px solid rgba(34, 211, 238, 0.15)',
  borderRadius: 8,
  padding: '8px 12px',
  color: '#e6f1ff',
  fontSize: 13,
  outline: 'none',
  width: 340,
};

const hintStyle: React.CSSProperties = { fontSize: 11, color: '#5A7182', margin: '0 0 0 116px' };

const testBtnStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '8px 16px',
  borderRadius: 8,
  border: '1px solid rgba(34, 211, 238, 0.2)',
  background: 'rgba(34, 211, 238, 0.05)',
  color: '#22d3ee',
  fontSize: 12,
  cursor: 'pointer',
};

function SectionCard({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: 'rgba(8, 14, 28, 0.4)', border: '1px solid rgba(34, 211, 238, 0.08)', borderRadius: 12, padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ color: '#22d3ee' }}>{icon}</span>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7dd3fc' }}>
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}

function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      {label ? (
        <label style={{ color: '#5A7182', fontSize: 12, minWidth: 100, textAlign: 'right' }}>{label}</label>
      ) : (
        <div style={{ minWidth: 100 }} />
      )}
      {children}
    </div>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  displayValue,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  displayValue: string;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <label style={{ color: '#7dd3fc', fontSize: 12 }}>{label}</label>
        <span style={{ color: '#22d3ee', fontSize: 11, fontFamily: 'monospace' }}>{displayValue}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{
          width: '100%',
          height: 4,
          WebkitAppearance: 'none',
          appearance: 'none',
          background: `linear-gradient(90deg, #22d3ee ${pct}%, rgba(255,255,255,0.08) ${pct}%)`,
          borderRadius: 2,
          outline: 'none',
          cursor: 'pointer',
        }}
      />
    </div>
  );
}
