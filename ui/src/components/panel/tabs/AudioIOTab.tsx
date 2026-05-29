import { useEffect, useState } from 'react';
import { Volume2, Mic, Speaker } from 'lucide-react';
import { api, type AudioDevices } from '@/lib/api';
import { SaveBar } from './WakeWordTab';

/**
 * Audio I/O. Device pickers are NAME-based — they save the device name to the
 * config keys the backend actually reads (`wispr_mic_device` for the mic,
 * `tts_output_device` for the speaker). Names survive index changes when
 * wireless/USB devices reconnect, unlike the old (dead) *_device_index keys.
 */
export default function AudioIOTab() {
  const [devices, setDevices] = useState<AudioDevices>({
    inputs: [],
    outputs: [],
    current_in: null,
    current_out: null,
  });
  const [micName, setMicName] = useState<string>('');     // wispr_mic_device
  const [outName, setOutName] = useState<string>('');     // tts_output_device
  const [vadLevel, setVadLevel] = useState(1);
  const [threshold, setThreshold] = useState(0.005);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api.audioDevices().then(setDevices).catch(() => {});
    api
      .getConfig()
      .then((cfg) => {
        setMicName(cfg.wispr_mic_device == null ? '' : String(cfg.wispr_mic_device));
        setOutName(cfg.tts_output_device == null ? '' : String(cfg.tts_output_device));
        setVadLevel(Number(cfg.vad_aggressiveness ?? 1));
        setThreshold(Number(cfg.voice_min_energy ?? 0.005));
      })
      .catch(() => {});
  }, []);

  const save = async () => {
    await api.patchConfig({
      wispr_mic_device: micName.trim() === '' ? null : micName,
      tts_output_device: outName.trim() === '' ? null : outName,
      vad_aggressiveness: vadLevel,
      voice_min_energy: threshold,
    });
    setDirty(false);
    setSavedAt(Date.now());
  };

  const playTone = () => api.testTone().catch(() => {});

  // De-duplicate by name — the backend lists every host-API variant of the same
  // physical device; the user only needs to pick the name once.
  const uniq = (list: { index: number; name: string }[]) =>
    [...new Map(list.map((d) => [d.name, d])).values()];
  const inputs = uniq(devices.inputs);
  const outputs = uniq(devices.outputs);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, maxWidth: 700 }}>
      <SectionCard icon={<Mic size={18} />} title="Input (Microphone)">
        <FormRow label="Microphone">
          <select
            value={micName}
            onChange={(e) => {
              setMicName(e.target.value);
              setDirty(true);
            }}
            style={selectStyle}
          >
            <option value="">(System Default)</option>
            {inputs.map((d) => (
              <option key={d.name} value={d.name}>
                {d.name}
              </option>
            ))}
            {micName && !inputs.some((d) => d.name === micName) && (
              <option value={micName}>{micName} (not detected)</option>
            )}
          </select>
        </FormRow>
        <p style={hintStyle}>Where Jarvis listens for "Hey Jarvis".</p>
      </SectionCard>

      <SectionCard icon={<Speaker size={18} />} title="Output (Speaker)">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <FormRow label="Speaker">
            <select
              value={outName}
              onChange={(e) => {
                setOutName(e.target.value);
                setDirty(true);
              }}
              style={selectStyle}
            >
              <option value="">(Follow Windows default)</option>
              {outputs.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name}
                </option>
              ))}
              {outName && !outputs.some((d) => d.name === outName) && (
                <option value={outName}>{outName} (not detected)</option>
              )}
            </select>
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
