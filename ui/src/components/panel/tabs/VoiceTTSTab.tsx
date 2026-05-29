import { useEffect, useState } from 'react';
import { Trash2, Gauge } from 'lucide-react';
import { api, type TTSCacheStats } from '@/lib/api';
import { SaveBar } from './WakeWordTab';

/**
 * Voice (TTS) settings. The system uses Piper by default — a local, near-instant
 * voice engine. Only practical controls are exposed: which engine, and how fast
 * Jarvis speaks. Advanced per-engine tuning lives in config.json.
 */
export default function VoiceTTSTab() {
  const [engine, setEngine] = useState<'piper' | 'chatterbox'>('piper');
  // Piper length_scale: <1.0 = faster speech, >1.0 = slower. Default 0.65.
  const [speed, setSpeed] = useState(0.65);
  const [stats, setStats] = useState<TTSCacheStats>({ hits: 0, misses: 0, size_bytes: 0, count: 0 });
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        setEngine((cfg.tts_engine as 'piper' | 'chatterbox') ?? 'piper');
        setSpeed(Number(cfg.tts_piper_length_scale ?? 0.65));
      })
      .catch(() => {});
    api.ttsCacheStats().then(setStats).catch(() => {});
  }, []);

  const save = async () => {
    await api.patchConfig({
      tts_engine: engine,
      tts_piper_length_scale: speed,
    });
    setDirty(false);
    setSavedAt(Date.now());
  };

  const clearCache = async () => {
    await api.clearTTSCache().catch(() => {});
    const s = await api.ttsCacheStats().catch(() => null);
    if (s) setStats(s);
  };

  const fmtSize = (b: number) => {
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${(b / 1024 / 1024).toFixed(1)} MB`;
  };

  const ENGINES: { id: 'piper' | 'chatterbox'; label: string; hint: string }[] = [
    { id: 'piper', label: 'Piper', hint: 'Fast & local (recommended)' },
    { id: 'chatterbox', label: 'Chatterbox', hint: 'Higher quality · slower · uses GPU' },
  ];

  // Speed slider: left = faster (low length_scale), right = slower (high).
  const speedPct = ((speed - 0.5) / (1.5 - 0.5)) * 100;
  const speedLabel = speed <= 0.7 ? 'Fast' : speed >= 1.1 ? 'Slow' : 'Normal';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, maxWidth: 700 }}>
      <Card>
        <span style={labelStyle}>Voice Engine</span>
        <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
          {ENGINES.map((eng) => (
            <button
              key={eng.id}
              onClick={() => {
                setEngine(eng.id);
                setDirty(true);
              }}
              style={{
                flex: 1,
                padding: '14px 18px',
                borderRadius: 10,
                textAlign: 'left',
                border: `1px solid ${engine === eng.id ? 'rgba(34, 211, 238, 0.4)' : 'rgba(255,255,255,0.08)'}`,
                background: engine === eng.id ? 'rgba(34, 211, 238, 0.1)' : 'rgba(255,255,255,0.02)',
                color: engine === eng.id ? '#22d3ee' : '#8aa0b2',
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            >
              <div style={{ fontSize: 14, fontWeight: 600 }}>{eng.label}</div>
              <div style={{ fontSize: 11, color: '#5A7182', marginTop: 4 }}>{eng.hint}</div>
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <Gauge size={16} color="#22d3ee" />
          <span style={labelStyle}>Speaking Speed</span>
          <span style={{ marginLeft: 'auto', color: '#22d3ee', fontSize: 12, fontFamily: 'monospace' }}>
            {speedLabel} · {speed.toFixed(2)}
          </span>
        </div>
        <input
          type="range"
          min={0.5}
          max={1.5}
          step={0.05}
          value={speed}
          onChange={(e) => {
            setSpeed(Number(e.target.value));
            setDirty(true);
          }}
          style={sliderStyle(speedPct)}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
          <span style={{ fontSize: 11, color: '#5A7182' }}>← Faster</span>
          <span style={{ fontSize: 11, color: '#5A7182' }}>Slower →</span>
        </div>
        <p style={{ fontSize: 11, color: '#5A7182', marginTop: 8 }}>
          Applies to Piper. Lower = quicker replies.
        </p>
      </Card>

      <Card>
        <span style={labelStyle}>TTS Cache</span>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, margin: '16px 0' }}>
          <StatBox label="Hits" value={String(stats.hits)} color="#34d399" />
          <StatBox label="Misses" value={String(stats.misses)} color="#fbbf24" />
          <StatBox label="Entries" value={String(stats.count)} color="#22d3ee" />
          <StatBox label="Size" value={fmtSize(stats.size_bytes)} color="#22d3ee" />
        </div>
        <button onClick={clearCache} style={clearBtnStyle}>
          <Trash2 size={14} />
          Clear Cache
        </button>
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

const clearBtnStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  padding: '8px 14px',
  borderRadius: 8,
  border: '1px solid rgba(248, 113, 113, 0.2)',
  background: 'rgba(248, 113, 113, 0.05)',
  color: '#f87171',
  fontSize: 12,
  cursor: 'pointer',
};

function sliderStyle(pct: number): React.CSSProperties {
  return {
    width: '100%',
    height: 4,
    WebkitAppearance: 'none',
    appearance: 'none',
    background: `linear-gradient(90deg, #22d3ee ${pct}%, rgba(255,255,255,0.08) ${pct}%)`,
    borderRadius: 2,
    outline: 'none',
    cursor: 'pointer',
  };
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ background: 'rgba(8, 14, 28, 0.4)', border: '1px solid rgba(34, 211, 238, 0.08)', borderRadius: 12, padding: 20 }}>
      {children}
    </div>
  );
}

function StatBox({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ background: 'rgba(5, 11, 25, 0.5)', borderRadius: 8, padding: 12, textAlign: 'center' }}>
      <div style={{ fontSize: 18, fontWeight: 600, color, fontFamily: "'JetBrains Mono', monospace", marginBottom: 4 }}>
        {value}
      </div>
      <div style={{ fontSize: 10, color: '#5A7182', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</div>
    </div>
  );
}
