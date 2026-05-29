import { useEffect, useState } from 'react';
import { Brain } from 'lucide-react';
import { api } from '@/lib/api';
import { SaveBar } from './WakeWordTab';

/**
 * Language Model. Only the chat model picker is exposed — it's the one control
 * that's actually wired (ollama_chat_model). The old system-prompt / temperature
 * / max-tokens fields were removed: they wrote to config keys that don't exist,
 * so "saving" them did nothing.
 */
export default function LanguageModelTab() {
  const [model, setModel] = useState('');
  const [available, setAvailable] = useState<{ name: string; size: number }[]>([]);
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => setModel(String(cfg.ollama_chat_model ?? '')))
      .catch(() => {});
    api.llmModels().then(setAvailable).catch(() => setAvailable([]));
  }, []);

  const fmtSize = (b: number) => `${(b / 1024 / 1024 / 1024).toFixed(1)} GB`;

  const save = async () => {
    await api.patchConfig({ ollama_chat_model: model });
    setDirty(false);
    setSavedAt(Date.now());
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, maxWidth: 700 }}>
      <div style={{ background: 'rgba(8, 14, 28, 0.4)', border: '1px solid rgba(34, 211, 238, 0.08)', borderRadius: 12, padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <Brain size={16} color="#22d3ee" />
          <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7dd3fc' }}>
            Chat Model ({available.length} installed)
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
            width: 340,
          }}
        >
          {available.length === 0 && <option value={model}>{model || '(none)'}</option>}
          {available.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name} ({fmtSize(m.size)})
            </option>
          ))}
        </select>
        <p style={{ fontSize: 11, color: '#5A7182', marginTop: 12, maxWidth: 520, lineHeight: 1.5 }}>
          The brain that writes Jarvis's replies. Bigger models are smarter but slower; smaller
          ones answer faster. Takes effect on the next restart.
        </p>
      </div>

      <SaveBar dirty={dirty} onSave={save} savedAt={savedAt} />
    </div>
  );
}
