import { useEffect, useState } from 'react';
import { api, openStateStream, type VoiceStatePayload } from '@/lib/api';

const STATE_META: Record<VoiceStatePayload['state'], { emoji: string; label: string; color: string }> = {
  idle: { emoji: '💤', label: 'Idle', color: '#4a5568' },
  listening: { emoji: '🎤', label: 'Listening', color: '#4fd1c5' },
  thinking: { emoji: '🧠', label: 'Processing', color: '#a78bfa' },
  synthesizing: { emoji: '⚡', label: 'Synthesizing', color: '#a78bfa' },
  speaking: { emoji: '🔊', label: 'Speaking', color: '#f6ad55' },
};

export default function StatusBar() {
  const [state, setState] = useState<VoiceStatePayload | null>(null);
  const [connected, setConnected] = useState(true);

  useEffect(() => {
    const close = openStateStream((s) => {
      setState(s);
      setConnected(true);
    });
    return close;
  }, []);

  useEffect(() => {
    const check = () => {
      api.health().then(() => setConnected(true)).catch(() => setConnected(false));
    };
    check();
    const id = setInterval(check, 5000);
    return () => clearInterval(id);
  }, []);

  const meta = state ? STATE_META[state.state] : STATE_META.idle;
  const uptime = state ? formatUptime(state.uptime) : '--:--:--';

  return (
    <div
      style={{
        height: 24,
        background: '#0d1117',
        borderTop: '1px solid #1a2a3a',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 14px',
        flexShrink: 0,
        fontSize: 11,
        color: '#4a5568',
        letterSpacing: '0.02em',
        position: 'relative',
        zIndex: 2,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 120 }}>
        <span style={{ fontSize: 12 }}>{meta.emoji}</span>
        <span style={{ color: meta.color, fontWeight: 500 }}>{meta.label}</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, opacity: 0.6 }}>
        <span>UP {uptime}</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 120, justifyContent: 'flex-end' }}>
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: connected ? '#34d399' : '#fc8181',
            boxShadow: connected
              ? '0 0 4px rgba(52, 211, 153, 0.5)'
              : '0 0 4px rgba(252, 129, 129, 0.5)',
          }}
        />
        <span>{connected ? 'Connected' : 'Offline'}</span>
        <span style={{ marginLeft: 8, opacity: 0.5 }}>v2.0.0-alpha</span>
      </div>
    </div>
  );
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}
