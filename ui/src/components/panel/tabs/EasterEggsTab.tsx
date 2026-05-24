import { useEffect, useState } from 'react';
import { Film } from 'lucide-react';
import ToggleSwitch from '../shared/ToggleSwitch';
import { api, type EasterEgg } from '@/lib/api';

export default function EasterEggsTab() {
  const [eggs, setEggs] = useState<EasterEgg[]>([]);

  useEffect(() => {
    api.eastereggs().then(setEggs).catch(() => setEggs([]));
  }, []);

  const toggle = async (id: string, currentlyEnabled: boolean) => {
    setEggs((prev) => prev.map((e) => (e.id === id ? { ...e, enabled: !currentlyEnabled } : e)));
    try {
      await api.toggleEgg(id, !currentlyEnabled);
    } catch {
      /* revert handled on refresh */
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
        <Film size={16} color="#22d3ee" />
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#7dd3fc' }}>
          Easter Egg Collection
        </span>
        <span style={{ fontSize: 11, color: '#5A7182', marginLeft: 8 }}>{eggs.length} items</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {eggs.map((egg) => (
          <div
            key={egg.id}
            style={{
              background: 'rgba(8, 14, 28, 0.4)',
              border: '1px solid rgba(34, 211, 238, 0.06)',
              borderRadius: 12,
              padding: 16,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'flex-start',
              gap: 16,
              opacity: egg.enabled ? 1 : 0.5,
              transition: 'opacity 0.2s',
            }}
          >
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 14, fontWeight: 500, color: '#e6f1ff' }}>{egg.name}</span>
                {egg.enabled && (
                  <span
                    style={{
                      fontSize: 9,
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: 'rgba(244, 114, 182, 0.15)',
                      color: '#f472b6',
                      fontWeight: 600,
                      letterSpacing: '0.06em',
                    }}
                  >
                    ACTIVE
                  </span>
                )}
              </div>

              <p style={{ color: '#5A7182', fontSize: 12, margin: '0 0 8px' }}>{egg.description}</p>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {(egg.triggers || []).map((trigger, i) => (
                  <span
                    key={i}
                    style={{
                      padding: '3px 8px',
                      borderRadius: 6,
                      background: 'rgba(34, 211, 238, 0.06)',
                      border: '1px solid rgba(34, 211, 238, 0.1)',
                      color: '#7dd3fc',
                      fontSize: 10,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    "{trigger}"
                  </span>
                ))}
              </div>
            </div>

            <ToggleSwitch enabled={egg.enabled} onChange={() => toggle(egg.id, egg.enabled)} />
          </div>
        ))}

        {eggs.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', color: '#5A7182', fontSize: 13 }}>
            No easter eggs registered.
          </div>
        )}
      </div>
    </div>
  );
}
