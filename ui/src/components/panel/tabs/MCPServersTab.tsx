import { useEffect, useState } from 'react';
import { Cloud, Music, Mail, Calendar, FileText, Globe, AppWindow } from 'lucide-react';
import ToggleSwitch from '../shared/ToggleSwitch';
import { api, type MCPInfo } from '@/lib/api';

const ICONS: Record<string, React.ReactNode> = {
  weather: <Cloud size={20} />,
  spotify: <Music size={20} />,
  gmail: <Mail size={20} />,
  calendar: <Calendar size={20} />,
  notes: <FileText size={20} />,
  browser: <Globe size={20} />,
  apps: <AppWindow size={20} />,
};

export default function MCPServersTab() {
  const [servers, setServers] = useState<MCPInfo[]>([]);

  const refresh = () => api.mcps().then(setServers).catch(() => {});

  useEffect(() => {
    refresh();
  }, []);

  const toggleServer = async (id: string, currentlyEnabled: boolean) => {
    setServers((prev) =>
      prev.map((s) =>
        s.id === id
          ? { ...s, enabled: !currentlyEnabled, status: !currentlyEnabled ? 'connected' : 'disconnected' }
          : s
      )
    );
    try {
      await api.toggleMcp(id, !currentlyEnabled);
    } catch {
      refresh();
    }
  };

  return (
    <div>
      <p style={{ fontSize: 12, color: '#5A7182', margin: '0 0 16px', maxWidth: 640, lineHeight: 1.5 }}>
        Each service gives Jarvis an ability. Turn one off to disable it — e.g. switch off
        Spotify to stop music commands, or Gmail to stop email reading. Changes apply on the next restart.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 16 }}>
        {servers.map((server) => (
          <ServerCard
            key={server.id}
            server={server}
            onToggle={() => toggleServer(server.id, server.enabled)}
          />
        ))}
        {servers.length === 0 && (
          <div style={{ color: '#5A7182', fontSize: 12, padding: 20 }}>
            No MCP servers reported by the daemon.
          </div>
        )}
      </div>
    </div>
  );
}

function ServerCard({ server, onToggle }: { server: MCPInfo; onToggle: () => void }) {
  return (
    <div
      style={{
        background: 'rgba(8, 14, 28, 0.4)',
        border: `1px solid ${server.enabled ? 'rgba(34, 211, 238, 0.15)' : 'rgba(255,255,255,0.05)'}`,
        borderRadius: 12,
        padding: 20,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        transition: 'all 0.2s',
        opacity: server.enabled ? 1 : 0.6,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ color: server.enabled ? '#22d3ee' : '#5A7182' }}>{ICONS[server.id] ?? <Cloud size={20} />}</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 500, color: '#e6f1ff' }}>{server.name}</div>
            <div style={{ fontSize: 10, color: '#5A7182', fontFamily: 'monospace' }}>v{server.version}</div>
          </div>
        </div>
        <ToggleSwitch enabled={server.enabled} onChange={onToggle} />
      </div>

      <p style={{ fontSize: 12, color: '#5A7182', margin: 0 }}>{server.description}</p>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 'auto' }}>
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: server.status === 'connected' ? '#34d399' : '#f87171',
            boxShadow:
              server.status === 'connected'
                ? '0 0 6px rgba(52, 211, 153, 0.5)'
                : '0 0 6px rgba(248, 113, 113, 0.3)',
          }}
        />
        <span
          style={{
            fontSize: 11,
            color: server.status === 'connected' ? '#34d399' : '#f87171',
          }}
        >
          {server.status === 'connected' ? 'On' : 'Off'}
        </span>
      </div>
    </div>
  );
}
