import { useEffect, useState } from 'react';
import { Volume2, Mic, Speaker } from 'lucide-react';
import { api, type AudioDevices } from '@/lib/api';
import { SaveBar } from './WakeWordTab';

export default function AudioIOTab() {
  const [devices, setDevices] = useState<AudioDevices>({
    inputs: [],
    outputs: [],
    current_in: null,
    current_out: null,
  });
  const [inputIdx, setInputIdx] = useState<number | null>(null);
  const [outputIdx, setOutputIdx] = useState<number | null>(null);
  const [vadLevel, setVadLevel] = useState(1);
  const [threshold, setThreshold] = useState(0.005);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api
      .audioDevices()
      .then((d) => {
        setDevices(d);
        setInputIdx(d.current_in);
        setOutputIdx(d.current_out);
      })
      .catch(() => {});
    api
      .getConfig()
      .then((cfg) => {
        setVadLevel(Number(cfg.vad_aggressiveness ?? 1));
        setThreshold(Number(cfg.voice_min_energy ?? 0.005));
      })
      .catch(() => {});
  }, []);

  const save = async () => {
    await api.patchConfig({
      vad_aggressiveness: vadLevel,
      voice_min_energy: threshold,
      audio_input_device_index: inputIdx,
      audio_output_device_index: outputIdx,
    });
    setDirty(false);
    setSavedAt(Date.now());
  };

  const playTone = () => api.testTone().catch(() => {});

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, maxWidth: 700 }}>
      <SectionCard icon={<Mic size={18} />} title="Input (Microphone)">
        <FormRow label="Microphone">
          <select
            value={inputIdx ?? ''}
            onChange={(e) => {
              setInputIdx(e.target.value === '' ? null : Number(e.target.value));
              setDirty(true);
            }}
            style={selectStyle}
          >
            <option value="">(System Default)</option>
            {devices.inputs.map((d) => (
              <option key={d.index} value={d.index}>
                {d.name}
              </option>
            ))}
          </select>
        </FormRow>
      </SectionCard>

      <SectionCard icon={<Speaker size={18} />} title="Output (Speaker)">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <FormRow label="Speaker">
            <select
              value={outputIdx ?? ''}
              onChange={(e) => {
                setOutputIdx(e.target.value === '' ? null : Number(e.target.value));
                setDirty(true);
              }}
              style={selectStyle}
            >
              <option value="">(System Default)</option>
              {devices.outputs.map((d) => (
                <option key={d.index} value={d.index}>
                  {d.name}
                </option>
              ))}
            </select>
          </FormRow>
          <FormRow label="">
            <button
              onClick={playTone}
              style={{
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
              }}
            >
              <Volume2 size={14} />
              Test Tone
            </button>
          </FormRow>
        </div>
      </SectionCard>

      <SectionCard icon={<Volume2 size={18} />} title="Voice Activity Detection">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <SliderRow
            label="VAD Aggressiveness"
            value={vadLevel}
            min={0}
            max={3}
            step={1}
            onChange={(v) => {
              setVadLevel(v);
              setDirty(true);
            }}
            displayValue={['Disabled', 'Low', 'Medium', 'High'][vadLevel]}
          />
          <SliderRow
            label="Mic Energy Threshold"
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
  width: 320,
};

function SectionCard({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: 'rgba(8, 14, 28, 0.4)',
        border: '1px solid rgba(34, 211, 238, 0.08)',
        borderRadius: 12,
        padding: 20,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ color: '#22d3ee' }}>{icon}</span>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: '#7dd3fc',
          }}
        >
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
      {label && (
        <label style={{ color: '#5A7182', fontSize: 12, minWidth: 100, textAlign: 'right' }}>
          {label}
        </label>
      )}
      {!label && <div style={{ minWidth: 100 }} />}
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
