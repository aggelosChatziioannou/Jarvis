import { useEffect, useState } from 'react';
import { X, Plus, Ear, Save } from 'lucide-react';
import { api } from '@/lib/api';

/**
 * Wake Word settings. Two practical controls:
 *  - Aliases: extra phrases that wake Jarvis (Greek + English variants).
 *  - Wake sensitivity: how easily "Hey Jarvis" triggers (wispr_wake_threshold).
 * (The old Porcupine engine section was removed — Jarvis now uses openWakeWord,
 * so those knobs did nothing.)
 */
export default function WakeWordTab() {
  const [aliases, setAliases] = useState<string[]>([]);
  const [newAlias, setNewAlias] = useState('');
  const [threshold, setThreshold] = useState(0.1); // wispr_wake_threshold
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        setAliases((cfg.wake_aliases as string[]) || []);
        setThreshold(Number(cfg.wispr_wake_threshold ?? 0.1));
      })
      .catch(() => {});
  }, []);

  const addAlias = () => {
    const v = newAlias.trim();
    if (v && !aliases.includes(v)) {
      setAliases([...aliases, v]);
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
      wispr_wake_threshold: threshold,
    });
    setDirty(false);
    setSavedAt(Date.now());
  };

  // Slider: low threshold = triggers easily; high = needs a clear "Jarvis".
  const pct = ((threshold - 0.05) / (0.9 - 0.05)) * 100;
  const sens = threshold <= 0.15 ? 'Easy to trigger' : threshold >= 0.5 ? 'Strict' : 'Balanced';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, maxWidth: 600 }}>
      {/* Aliases */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <Ear size={16} color="#22d3ee" />
          <span style={labelStyle}>Wake Phrases ({aliases.length})</span>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
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
              <button onClick={() => removeAlias(i)} style={chipX}>
                <X size={14} />
              </button>
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <input
              type="text"
              placeholder="Add phrase..."
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
                width: 150,
              }}
            />
            <button onClick={addAlias} style={addBtn}>
              <Plus size={16} />
            </button>
          </div>
        </div>
        <p style={{ fontSize: 11, color: '#5A7182', marginTop: 12 }}>
          Extra phrases that wake Jarvis (e.g. "τζάρβις", "hey jarvis").
        </p>
      </Card>

      {/* Wake sensitivity */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <span style={labelStyle}>Wake Sensitivity</span>
          <span style={{ marginLeft: 'auto', color: '#22d3ee', fontSize: 12, fontFamily: 'monospace' }}>
            {sens} · {threshold.toFixed(2)}
          </span>
        </div>
        <input
          type="range"
          min={0.05}
          max={0.9}
          step={0.05}
          value={threshold}
          onChange={(e) => {
            setThreshold(Number(e.target.value));
            setDirty(true);
          }}
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
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
          <span style={{ fontSize: 11, color: '#5A7182' }}>← Triggers easily</span>
          <span style={{ fontSize: 11, color: '#5A7182' }}>Needs clear "Jarvis" →</span>
        </div>
        <p style={{ fontSize: 11, color: '#5A7182', marginTop: 8 }}>
          If Jarvis wakes by accident, move right. If it misses you, move left.
        </p>
      </Card>

      <SaveBar dirty={dirty} onSave={save} savedAt={savedAt} />
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: '0.1em',
  textTransform: 'uppercase',
  color: '#7dd3fc',
};

const chipX: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#5A7182',
  cursor: 'pointer',
  padding: 0,
  display: 'flex',
  alignItems: 'center',
};

const addBtn: React.CSSProperties = {
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
};

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ background: 'rgba(8, 14, 28, 0.4)', border: '1px solid rgba(34, 211, 238, 0.08)', borderRadius: 12, padding: 20 }}>
      {children}
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
