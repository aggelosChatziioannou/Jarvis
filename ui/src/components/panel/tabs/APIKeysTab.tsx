import { useEffect, useState } from 'react';
import { Key, Eye, EyeOff } from 'lucide-react';
import { api } from '@/lib/api';
import { SaveBar } from './WakeWordTab';

interface KeyField {
  id: string;
  configKey: string;
  label: string;
  type: 'text' | 'email' | 'password';
  help: string;
}

// Only keys that real Jarvis features use. (The Picovoice/Porcupine key was
// removed — Jarvis no longer uses Porcupine for wake detection.)
const FIELDS: KeyField[] = [
  { id: 'spotify-client', configKey: 'spotify_client_id', label: 'Spotify Client ID', type: 'text', help: 'From developer.spotify.com → your app → Settings.' },
  { id: 'spotify-secret', configKey: 'spotify_client_secret', label: 'Spotify Client Secret', type: 'password', help: 'Same page as the Client ID (click "View client secret").' },
  { id: 'weather', configKey: 'openweather_api_key', label: 'OpenWeather API Key', type: 'password', help: 'Free key from openweathermap.org/api.' },
  { id: 'gmail-addr', configKey: 'gmail_address', label: 'Gmail Address', type: 'email', help: 'The Gmail account Jarvis reads/sends from.' },
  { id: 'gmail-pass', configKey: 'gmail_app_password', label: 'Gmail App Password', type: 'password', help: 'Google Account → Security → App passwords (needs 2-step verification).' },
];

export default function APIKeysTab() {
  const [values, setValues] = useState<Record<string, string>>({});
  const [visible, setVisible] = useState<Set<string>>(new Set());
  const [dirty, setDirty] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    api
      .getConfig()
      .then((cfg) => {
        const v: Record<string, string> = {};
        FIELDS.forEach((f) => {
          v[f.id] = String(cfg[f.configKey] ?? '');
        });
        setValues(v);
      })
      .catch(() => {});
  }, []);

  const toggleVisible = (id: string) => {
    setVisible((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const update = (id: string, value: string) => {
    setValues((prev) => ({ ...prev, [id]: value }));
    setDirty(true);
  };

  const save = async () => {
    const updates: Record<string, string> = {};
    FIELDS.forEach((f) => {
      updates[f.configKey] = values[f.id] ?? '';
    });
    await api.patchConfig(updates);
    setDirty(false);
    setSavedAt(Date.now());
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 700 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <Key size={16} color="#22d3ee" />
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7dd3fc' }}>
          Connected Accounts
        </span>
      </div>

      {FIELDS.map((key) => {
        const isVisible = visible.has(key.id);
        const isPassword = key.type === 'password';
        const value = values[key.id] ?? '';

        return (
          <div
            key={key.id}
            style={{
              background: 'rgba(8, 14, 28, 0.4)',
              border: '1px solid rgba(34, 211, 238, 0.08)',
              borderRadius: 12,
              padding: 16,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <label style={{ color: '#7dd3fc', fontSize: 12, minWidth: 180, flexShrink: 0 }}>
                {key.label}
              </label>
              <input
                type={isPassword && !isVisible ? 'password' : key.type === 'email' ? 'email' : 'text'}
                value={value}
                onChange={(e) => update(key.id, e.target.value)}
                style={{
                  flex: 1,
                  background: 'rgba(5, 11, 25, 0.5)',
                  border: '1px solid rgba(34, 211, 238, 0.1)',
                  borderRadius: 8,
                  padding: '8px 12px',
                  color: '#e6f1ff',
                  fontSize: 13,
                  fontFamily: isPassword ? "'JetBrains Mono', monospace" : "'Inter', sans-serif",
                  outline: 'none',
                }}
              />
              {isPassword && (
                <button onClick={() => toggleVisible(key.id)} style={eyeBtn}>
                  {isVisible ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              )}
            </div>
            <p style={{ color: '#5A7182', fontSize: 11, margin: '8px 0 0 192px' }}>{key.help}</p>
          </div>
        );
      })}

      <p style={{ color: '#5A7182', fontSize: 11, marginTop: 4 }}>
        Stored locally in <code style={{ color: '#7dd3fc' }}>~/.config/jarvis/config.json</code>. Leave a field blank to disable that feature.
      </p>

      <SaveBar dirty={dirty} onSave={save} savedAt={savedAt} />
    </div>
  );
}

const eyeBtn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  color: '#5A7182',
  cursor: 'pointer',
  padding: 4,
  display: 'flex',
  alignItems: 'center',
};
