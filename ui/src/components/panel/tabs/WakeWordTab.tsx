import { useEffect, useState } from 'react';
import { X, Plus, Ear, Save } from 'lucide-react';
import ToggleSwitch from '../shared/ToggleSwitch';
import { api } from '@/lib/api';

export default function WakeWordTab() {
  const [aliases, setAliases] = useState<string[]>([]);
  const [newAlias, setNewAlias] = useState('');
  const [porcupineEnabled, setPorcupineEnabled] = useState(false);
  const [sensitivity, setSensitivity] = useState(0.5);
  const [accessKey, setAccessKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        const a = (cfg.wake_aliases as string[]) || [];
        setAliases(a);
        setPorcupineEnabled(Boolean(cfg.porcupine_enabled));
        setSensitivity(Number(cfg.porcupine_sensitivity ?? 0.5));
        setAccessKey(String(cfg.porcupine_access_key ?? ''));
      })
      .catch(() => {});
  }, []);

  const addAlias = () => {
    if (newAlias.trim() && !aliases.includes(newAlias.trim())) {
      setAliases([...aliases, newAlias.trim()]);
      setNewAlias('');
      setDirty(true);
    }
  };

  const removeAlias = (idx: number) => {
    setAliases(aliases.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const save = async () => {
    await api.patchConfig({
      wake_aliases: aliases,
      porcupine_enabled: porcupineEnabled,
      porcupine_sensitivity: sensitivity,
      porcupine_access_key: accessKey,
    });
    setDirty(false);
    setSavedAt(Date.now());
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, maxWidth: 600 }}>
      {/* Aliases */}
      <div
        style={{
          background: 'rgba(8, 14, 28, 0.4)',
          border: '1px solid rgba(34, 211, 238, 0.08)',
          borderRadius: 12,
          padding: 20,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <Ear size={16} color="#22d3ee" />
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: '#7dd3fc',
            }}
          >
            Wake Aliases ({aliases.length})
          </span>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
          {aliases.map((alias, i) => (
            <div
              key={`${alias}-${i}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 12px',
                borderRadius: 8,
                background: 'rgba(34, 211, 238, 0.08)',
                border: '1px solid rgba(34, 211, 238, 0.15)',
                color: '#22d3ee',
                fontSize: 13,
              }}
            >
              <span>{alias}</span>
              <button
                onClick={() => removeAlias(i)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#5A7182',
                  cursor: 'pointer',
                  padding: 0,
                  display: 'flex',
                  alignItems: 'center',
                  transition: 'color 0.2s',
                }}
              >
                <X size={14} />
              </button>
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <input
              type="text"
              placeholder="Add alias..."
              value={newAlias}
              onChange={(e) => setNewAlias(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addAlias()}
              style={{
                background: 'rgba(8, 14, 28, 0.6)',
                border: '1px solid rgba(34, 211, 238, 0.15)',
                borderRadius: 8,
                padding: '6px 10px',
                color: '#e6f1ff',
                fontSize: 13,
                outline: 'none',
                width: 140,
              }}
            />
            <button
              onClick={addAlias}
              style={{
                marginLeft: 6,
                width: 32,
                height: 32,
                borderRadius: 8,
                background: 'rgba(34, 211, 238, 0.1)',
                border: '1px solid rgba(34, 211, 238, 0.2)',
                color: '#22d3ee',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Plus size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Porcupine Settings */}
      <div
        style={{
          background: 'rgba(8, 14, 28, 0.4)',
          border: '1px solid rgba(34, 211, 238, 0.08)',
          borderRadius: 12,
          padding: 20,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: '#7dd3fc',
            }}
          >
            Porcupine Engine
          </span>
          <ToggleSwitch
            enabled={porcupineEnabled}
            onChange={(v) => {
              setPorcupineEnabled(v);
              setDirty(true);
            }}
          />
        </div>

        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 20,
            opacity: porcupineEnabled ? 1 : 0.4,
            pointerEvents: porcupineEnabled ? 'auto' : 'none',
            transition: 'opacity 0.3s',
          }}
        >
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <label style={{ color: '#7dd3fc', fontSize: 12 }}>Sensitivity</label>
              <span style={{ color: '#22d3ee', fontSize: 11, fontFamily: 'monospace' }}>{sensitivity.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={sensitivity}
              onChange={(e) => {
                setSensitivity(Number(e.target.value));
                setDirty(true);
              }}
              style={{
                width: '100%',
                height: 4,
                WebkitAppearance: 'none',
                appearance: 'none',
                background: `linear-gradient(90deg, #22d3ee ${sensitivity * 100}%, rgba(255,255,255,0.08) ${sensitivity * 100}%)`,
                borderRadius: 2,
                outline: 'none',
                cursor: 'pointer',
              }}
            />
          </div>

          <div>
            <label style={{ color: '#7dd3fc', fontSize: 12, display: 'block', marginBottom: 8 }}>Access Key</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                type={showKey ? 'text' : 'password'}
                value={accessKey}
                onChange={(e) => {
                  setAccessKey(e.target.value);
                  setDirty(true);
                }}
                placeholder="pv_..."
                style={{
                  flex: 1,
                  background: 'rgba(8, 14, 28, 0.6)',
                  border: '1px solid rgba(34, 211, 238, 0.15)',
                  borderRadius: 8,
                  padding: '8px 12px',
                  color: '#e6f1ff',
                  fontSize: 13,
                  fontFamily: 'monospace',
                  outline: 'none',
                }}
              />
              <button
                onClick={() => setShowKey(!showKey)}
                style={{
                  padding: '8px 12px',
                  borderRadius: 8,
                  border: '1px solid rgba(255,255,255,0.1)',
                  background: 'rgba(255,255,255,0.03)',
                  color: '#5A7182',
                  fontSize: 11,
                  cursor: 'pointer',
                }}
              >
                {showKey ? 'Hide' : 'Show'}
              </button>
            </div>
          </div>
        </div>
      </div>

      <SaveBar dirty={dirty} onSave={save} savedAt={savedAt} />
    </div>
  );
}

export function SaveBar({
  dirty,
  onSave,
  savedAt,
}: {
  dirty: boolean;
  onSave: () => Promise<void> | void;
  savedAt: number | null;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <button
        onClick={() => void onSave()}
        disabled={!dirty}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '10px 18px',
          borderRadius: 10,
          border: `1px solid ${dirty ? 'rgba(34, 211, 238, 0.3)' : 'rgba(255,255,255,0.08)'}`,
          background: dirty ? 'rgba(34, 211, 238, 0.1)' : 'rgba(255,255,255,0.02)',
          color: dirty ? '#22d3ee' : '#5A7182',
          fontSize: 13,
          cursor: dirty ? 'pointer' : 'not-allowed',
          fontFamily: "'Inter', sans-serif",
        }}
      >
        <Save size={14} />
        Save Changes
      </button>
      {savedAt && !dirty && (
        <span style={{ fontSize: 11, color: '#34d399' }}>
          ✓ Saved at {new Date(savedAt).toLocaleTimeString()}
        </span>
      )}
    </div>
  );
}
