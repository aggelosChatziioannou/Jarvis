import { useEffect, useState } from 'react';
import { Languages } from 'lucide-react';
import ToggleSwitch from '../shared/ToggleSwitch';
import { api } from '@/lib/api';
import { SaveBar } from './WakeWordTab';

const WHISPER_MODELS = [
  'tiny', 'tiny.en', 'base', 'base.en', 'small', 'small.en',
  'medium', 'medium.en', 'large-v1', 'large-v2', 'large-v3',
];

const LANGUAGES = [
  { code: 'en', name: 'English', flag: '🇺🇸' },
  { code: 'el', name: 'Greek', flag: '🇬🇷' },
  { code: 'es', name: 'Spanish', flag: '🇪🇸' },
  { code: 'fr', name: 'French', flag: '🇫🇷' },
  { code: 'de', name: 'German', flag: '🇩🇪' },
  { code: 'it', name: 'Italian', flag: '🇮🇹' },
  { code: 'pt', name: 'Portuguese', flag: '🇵🇹' },
  { code: 'nl', name: 'Dutch', flag: '🇳🇱' },
  { code: 'ja', name: 'Japanese', flag: '🇯🇵' },
  { code: 'ko', name: 'Korean', flag: '🇰🇷' },
  { code: 'zh', name: 'Chinese', flag: '🇨🇳' },
];

export default function TranscriptionTab() {
  const [model, setModel] = useState('base');
  const [allowedLangs, setAllowedLangs] = useState<Set<string>>(new Set(['en', 'el']));
  const [confidence, setConfidence] = useState(0.6);
  const [prompt, setPrompt] = useState('Jarvis.');
  const [hallucinationFilter, setHallucinationFilter] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        setModel(String(cfg.whisper_model ?? 'base'));
        setAllowedLangs(new Set((cfg.whisper_allowed_languages as string[]) ?? ['en']));
        setConfidence(Number(cfg.whisper_min_confidence ?? 0.6));
        setPrompt(String(cfg.whisper_initial_prompt ?? 'Jarvis.'));
        setHallucinationFilter(cfg.whisper_filter_hallucinations !== false);
      })
      .catch(() => {});
  }, []);

  const toggleLang = (code: string) => {
    setAllowedLangs((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
    setDirty(true);
  };

  const save = async () => {
    await api.patchConfig({
      whisper_model: model,
      whisper_allowed_languages: Array.from(allowedLangs),
      whisper_min_confidence: confidence,
      whisper_initial_prompt: prompt,
      whisper_filter_hallucinations: hallucinationFilter,
    });
    setDirty(false);
    setSavedAt(Date.now());
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, maxWidth: 600 }}>
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <Languages size={16} color="#22d3ee" />
          <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7dd3fc' }}>
            Whisper Model
          </span>
        </div>
        <select
          value={model}
          onChange={(e) => {
            setModel(e.target.value);
            setDirty(true);
          }}
          style={{
            background: 'rgba(8, 14, 28, 0.6)',
            border: '1px solid rgba(34, 211, 238, 0.15)',
            borderRadius: 8,
            padding: '8px 12px',
            color: '#e6f1ff',
            fontSize: 13,
            outline: 'none',
            width: 200,
          }}
        >
          {WHISPER_MODELS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </Card>

      <Card>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7dd3fc', display: 'block', marginBottom: 12 }}>
          Allowed Languages
        </span>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {LANGUAGES.map((lang) => {
            const active = allowedLangs.has(lang.code);
            return (
              <button
                key={lang.code}
                onClick={() => toggleLang(lang.code)}
                style={{
                  padding: '6px 12px',
                  borderRadius: 8,
                  border: `1px solid ${active ? 'rgba(34, 211, 238, 0.3)' : 'rgba(255,255,255,0.06)'}`,
                  background: active ? 'rgba(34, 211, 238, 0.08)' : 'transparent',
                  color: active ? '#22d3ee' : '#5A7182',
                  fontSize: 12,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  transition: 'all 0.2s',
                }}
              >
                <span>{lang.flag}</span>
                <span>{lang.name}</span>
              </button>
            );
          })}
        </div>
      </Card>

      <Card>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <label style={{ color: '#7dd3fc', fontSize: 12 }}>Minimum Confidence</label>
            <span style={{ color: '#22d3ee', fontSize: 11, fontFamily: 'monospace' }}>{confidence.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={confidence}
            onChange={(e) => {
              setConfidence(Number(e.target.value));
              setDirty(true);
            }}
            style={{
              width: '100%',
              height: 4,
              WebkitAppearance: 'none',
              appearance: 'none',
              background: `linear-gradient(90deg, #22d3ee ${confidence * 100}%, rgba(255,255,255,0.08) ${confidence * 100}%)`,
              borderRadius: 2,
              outline: 'none',
              cursor: 'pointer',
            }}
          />
        </div>
      </Card>

      <Card>
        <label style={{ color: '#7dd3fc', fontSize: 12, display: 'block', marginBottom: 8 }}>
          Initial Prompt
        </label>
        <textarea
          value={prompt}
          onChange={(e) => {
            setPrompt(e.target.value);
            setDirty(true);
          }}
          rows={3}
          style={{
            width: '100%',
            background: 'rgba(8, 14, 28, 0.6)',
            border: '1px solid rgba(34, 211, 238, 0.15)',
            borderRadius: 8,
            padding: '10px 12px',
            color: '#e6f1ff',
            fontSize: 13,
            fontFamily: "'JetBrains Mono', monospace",
            outline: 'none',
            resize: 'vertical',
          }}
        />
      </Card>

      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <span style={{ color: '#7dd3fc', fontSize: 13 }}>Hallucination Filter</span>
            <p style={{ color: '#5A7182', fontSize: 11, marginTop: 4 }}>
              Filter repeated phrases and noise artifacts
            </p>
          </div>
          <ToggleSwitch
            enabled={hallucinationFilter}
            onChange={(v) => {
              setHallucinationFilter(v);
              setDirty(true);
            }}
          />
        </div>
      </Card>

      <SaveBar dirty={dirty} onSave={save} savedAt={savedAt} />
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ background: 'rgba(8, 14, 28, 0.4)', border: '1px solid rgba(34, 211, 238, 0.08)', borderRadius: 12, padding: 20 }}>
      {children}
    </div>
  );
}
