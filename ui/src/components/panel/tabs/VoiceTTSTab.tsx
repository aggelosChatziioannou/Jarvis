import { useEffect, useState } from 'react';
import { Trash2, Music } from 'lucide-react';
import { api, type TTSCacheStats } from '@/lib/api';
import { SaveBar } from './WakeWordTab';

export default function VoiceTTSTab() {
  const [engine, setEngine] = useState<'chatterbox' | 'piper'>('chatterbox');
  const [exaggeration, setExaggeration] = useState(1.0);
  const [cfgWeight, setCfgWeight] = useState(2.0);
  const [voicePath, setVoicePath] = useState('');
  const [stats, setStats] = useState<TTSCacheStats>({ hits: 0, misses: 0, size_bytes: 0, count: 0 });
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        setEngine((cfg.tts_engine as 'chatterbox' | 'piper') ?? 'chatterbox');
        setExaggeration(Number(cfg.tts_chatterbox_exaggeration ?? 1.0));
        setCfgWeight(Number(cfg.tts_chatterbox_cfg_weight ?? 2.0));
        setVoicePath(String(cfg.tts_chatterbox_audio_prompt ?? ''));
      })
      .catch(() => {});
    api.ttsCacheStats().then(setStats).catch(() => {});
  }, []);

  const save = async () => {
    await api.patchConfig({
      tts_engine: engine,
      tts_chatterbox_exaggeration: exaggeration,
      tts_chatterbox_cfg_weight: cfgWeight,
      tts_chatterbox_audio_prompt: voicePath,
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, maxWidth: 700 }}>
      <Card>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7dd3fc', display: 'block', marginBottom: 16 }}>
          TTS Engine
        </span>
        <div style={{ display: 'flex', gap: 12 }}>
          {(['chatterbox', 'piper'] as const).map((eng) => (
            <button
              key={eng}
              onClick={() => {
                setEngine(eng);
                setDirty(true);
              }}
              style={{
                flex: 1,
                padding: '12px 20px',
                borderRadius: 10,
                border: `1px solid ${engine === eng ? 'rgba(34, 211, 238, 0.4)' : 'rgba(255,255,255,0.08)'}`,
                background: engine === eng ? 'rgba(34, 211, 238, 0.1)' : 'rgba(255,255,255,0.02)',
                color: engine === eng ? '#22d3ee' : '#5A7182',
                fontSize: 13,
                fontWeight: 500,
                cursor: 'pointer',
                textTransform: 'capitalize',
                transition: 'all 0.2s',
              }}
            >
              {eng}
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <Music size={16} color="#22d3ee" />
          <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7dd3fc' }}>
            Voice Clone
          </span>
        </div>
        <input
          type="text"
          value={voicePath}
          onChange={(e) => {
            setVoicePath(e.target.value);
            setDirty(true);
          }}
          placeholder="C:\path\to\voice_sample.wav"
          style={{
            width: '100%',
            background: 'rgba(8, 14, 28, 0.6)',
            border: '1px solid rgba(34, 211, 238, 0.15)',
            borderRadius: 8,
            padding: '8px 12px',
            color: '#e6f1ff',
            fontSize: 12,
            fontFamily: 'monospace',
            outline: 'none',
          }}
        />
        <p style={{ fontSize: 11, color: '#5A7182', marginTop: 6 }}>
          Path to a 5–15 second WAV file. Chatterbox will clone this voice for all replies.
        </p>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Card>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <label style={{ color: '#7dd3fc', fontSize: 12 }}>Exaggeration</label>
              <span style={{ color: '#22d3ee', fontSize: 11, fontFamily: 'monospace' }}>{exaggeration.toFixed(1)}</span>
            </div>
            <input
              type="range"
              min={0.5}
              max={2}
              step={0.1}
              value={exaggeration}
              onChange={(e) => {
                setExaggeration(Number(e.target.value));
                setDirty(true);
              }}
              style={sliderStyle(((exaggeration - 0.5) / 1.5) * 100)}
            />
          </div>
        </Card>

        <Card>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <label style={{ color: '#7dd3fc', fontSize: 12 }}>CFG Weight</label>
              <span style={{ color: '#22d3ee', fontSize: 11, fontFamily: 'monospace' }}>{cfgWeight.toFixed(1)}</span>
            </div>
            <input
              type="range"
              min={1}
              max={5}
              step={0.1}
              value={cfgWeight}
              onChange={(e) => {
                setCfgWeight(Number(e.target.value));
                setDirty(true);
              }}
              style={sliderStyle(((cfgWeight - 1) / 4) * 100)}
            />
          </div>
        </Card>
      </div>

      <Card>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7dd3fc', display: 'block', marginBottom: 16 }}>
          TTS Cache
        </span>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
          <StatBox label="Hits" value={String(stats.hits)} color="#34d399" />
          <StatBox label="Misses" value={String(stats.misses)} color="#fbbf24" />
          <StatBox label="Entries" value={String(stats.count)} color="#22d3ee" />
          <StatBox label="Size" value={fmtSize(stats.size_bytes)} color="#22d3ee" />
        </div>
        <button
          onClick={clearCache}
          style={{
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
          }}
        >
          <Trash2 size={14} />
          Clear Cache
        </button>
      </Card>

      <SaveBar dirty={dirty} onSave={save} savedAt={savedAt} />
    </div>
  );
}

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
      <div style={{ fontSize: 10, color: '#5A7182', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {label}
      </div>
    </div>
  );
}
