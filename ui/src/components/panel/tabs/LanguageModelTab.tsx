import { useEffect, useState } from 'react';
import { Brain } from 'lucide-react';
import { api } from '@/lib/api';
import { SaveBar } from './WakeWordTab';

export default function LanguageModelTab() {
  const [model, setModel] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(256);
  const [available, setAvailable] = useState<{ name: string; size: number }[]>([]);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        setModel(String(cfg.ollama_chat_model ?? ''));
        setSystemPrompt(String(cfg.system_prompt ?? ''));
        setTemperature(Number(cfg.llm_temperature ?? 0.7));
        setMaxTokens(Number(cfg.llm_max_tokens ?? 256));
      })
      .catch(() => {});
    api.llmModels().then(setAvailable).catch(() => setAvailable([]));
  }, []);

  const fmtSize = (b: number) => `${(b / 1024 / 1024 / 1024).toFixed(1)} GB`;

  const save = async () => {
    await api.patchConfig({
      ollama_chat_model: model,
      system_prompt: systemPrompt,
      llm_temperature: temperature,
      llm_max_tokens: maxTokens,
    });
    setDirty(false);
    setSavedAt(Date.now());
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, maxWidth: 700 }}>
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <Brain size={16} color="#22d3ee" />
          <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7dd3fc' }}>
            Ollama Model ({available.length} installed)
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
            width: 320,
          }}
        >
          {available.length === 0 && <option value={model}>{model || '(none)'}</option>}
          {available.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name} ({fmtSize(m.size)})
            </option>
          ))}
        </select>
      </Card>

      <Card>
        <label style={{ color: '#7dd3fc', fontSize: 12, display: 'block', marginBottom: 8 }}>
          System Prompt
        </label>
        <textarea
          value={systemPrompt}
          onChange={(e) => {
            setSystemPrompt(e.target.value);
            setDirty(true);
          }}
          rows={10}
          placeholder="(leave blank to use Jarvis built-in prompt)"
          style={{
            width: '100%',
            background: 'rgba(8, 14, 28, 0.6)',
            border: '1px solid rgba(34, 211, 238, 0.15)',
            borderRadius: 8,
            padding: '12px',
            color: '#e6f1ff',
            fontSize: 13,
            fontFamily: "'JetBrains Mono', monospace",
            lineHeight: 1.6,
            outline: 'none',
            resize: 'vertical',
          }}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
          <span style={{ color: '#5A7182', fontSize: 11 }}>{systemPrompt.length} chars</span>
        </div>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Card>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <label style={{ color: '#7dd3fc', fontSize: 12 }}>Temperature</label>
              <span style={{ color: '#22d3ee', fontSize: 11, fontFamily: 'monospace' }}>{temperature.toFixed(1)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={2}
              step={0.1}
              value={temperature}
              onChange={(e) => {
                setTemperature(Number(e.target.value));
                setDirty(true);
              }}
              style={sliderStyle((temperature / 2) * 100)}
            />
          </div>
        </Card>

        <Card>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <label style={{ color: '#7dd3fc', fontSize: 12 }}>Max Tokens</label>
              <span style={{ color: '#22d3ee', fontSize: 11, fontFamily: 'monospace' }}>{maxTokens}</span>
            </div>
            <input
              type="range"
              min={64}
              max={1024}
              step={64}
              value={maxTokens}
              onChange={(e) => {
                setMaxTokens(Number(e.target.value));
                setDirty(true);
              }}
              style={sliderStyle(((maxTokens - 64) / 960) * 100)}
            />
          </div>
        </Card>
      </div>

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
