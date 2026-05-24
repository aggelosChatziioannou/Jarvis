import { useEffect, useRef, useState } from 'react';
import { Search, Pause, ArrowDown, Trash2, Download, Play } from 'lucide-react';
import { api, openLogStream, type LogPayload } from '@/lib/api';

const LEVEL_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  info: { bg: 'rgba(34, 211, 238, 0.1)', color: '#22d3ee', label: 'INFO' },
  warning: { bg: 'rgba(251, 191, 36, 0.1)', color: '#fbbf24', label: 'WARN' },
  error: { bg: 'rgba(248, 113, 113, 0.1)', color: '#f87171', label: 'ERROR' },
  'fast-path': { bg: 'rgba(52, 211, 153, 0.1)', color: '#34d399', label: 'FAST' },
  mcp: { bg: 'rgba(167, 139, 250, 0.1)', color: '#a78bfa', label: 'MCP' },
  'easter-egg': { bg: 'rgba(244, 114, 182, 0.1)', color: '#f472b6', label: 'EGG' },
};

const FILTER_CHIPS = [
  { key: 'info', label: 'Info', color: '#22d3ee' },
  { key: 'warning', label: 'Warning', color: '#fbbf24' },
  { key: 'error', label: 'Error', color: '#f87171' },
  { key: 'fast-path', label: 'Fast-path', color: '#34d399', icon: '⚡' },
  { key: 'mcp', label: 'MCP', color: '#a78bfa' },
  { key: 'easter-egg', label: 'Easter Egg', color: '#f472b6', icon: '🎬' },
];

export default function LiveLogsTab() {
  const [logs, setLogs] = useState<LogPayload[]>([]);
  const [search, setSearch] = useState('');
  const [activeFilters, setActiveFilters] = useState<Set<string>>(
    new Set(['info', 'warning', 'error', 'fast-path', 'mcp', 'easter-egg'])
  );
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const streamRef = useRef<LogPayload[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(false);
  pausedRef.current = paused;

  useEffect(() => {
    api.logs(500).then(setLogs).catch(() => {});
    const close = openLogStream((entry) => {
      streamRef.current = [...streamRef.current, entry].slice(-1000);
      if (!pausedRef.current) {
        setLogs((prev) => [...prev, entry].slice(-1000));
      }
    });
    return close;
  }, []);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const toggleFilter = (key: string) => {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const filtered = logs.filter((log) => {
    if (!activeFilters.has(log.level)) return false;
    if (search && !log.message.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const handleClear = async () => {
    await api.clearLogs().catch(() => {});
    setLogs([]);
    streamRef.current = [];
  };

  const handleExport = () => {
    const text = filtered
      .map((l) => `[${l.timestamp}] [${l.level.toUpperCase()}] ${l.message}`)
      .join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `jarvis-logs-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleResume = () => {
    setPaused(false);
    setLogs(streamRef.current.slice(-1000));
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 16 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            background: 'rgba(8, 14, 28, 0.6)',
            border: '1px solid rgba(34, 211, 238, 0.12)',
            borderRadius: 10,
            padding: '0 14px',
            height: 40,
          }}
        >
          <Search size={16} color="#5A7182" />
          <input
            type="text"
            placeholder="Search logs..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: '#e6f1ff',
              fontSize: 13,
              fontFamily: "'Inter', sans-serif",
            }}
          />
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {FILTER_CHIPS.map((chip) => {
            const active = activeFilters.has(chip.key);
            return (
              <button
                key={chip.key}
                onClick={() => toggleFilter(chip.key)}
                style={{
                  padding: '5px 12px',
                  borderRadius: 20,
                  border: `1px solid ${active ? chip.color : 'rgba(255,255,255,0.08)'}`,
                  background: active ? `${chip.color}15` : 'transparent',
                  color: active ? chip.color : '#5A7182',
                  fontSize: 11,
                  fontFamily: "'Inter', sans-serif",
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  transition: 'all 0.2s',
                  letterSpacing: '0.04em',
                }}
              >
                {chip.icon && <span>{chip.icon}</span>}
                {chip.label}
              </button>
            );
          })}
        </div>
      </div>

      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          background: 'rgba(5, 11, 25, 0.5)',
          borderRadius: 10,
          border: '1px solid rgba(34, 211, 238, 0.06)',
          fontFamily: "'JetBrains Mono', 'Consolas', monospace",
          fontSize: 12,
          maxHeight: 380,
        }}
      >
        {filtered.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: '#5A7182', fontSize: 12 }}>
            Waiting for logs...
          </div>
        )}
        {filtered.map((log) => {
          const style = LEVEL_STYLES[log.level] || LEVEL_STYLES.info;
          return (
            <div
              key={log.id}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 10,
                padding: '6px 12px',
                borderBottom: '1px solid rgba(255,255,255,0.03)',
              }}
            >
              <span style={{ color: '#3A5060', fontSize: 11, minWidth: 80, flexShrink: 0 }}>
                {log.timestamp}
              </span>
              <span
                style={{
                  background: style.bg,
                  color: style.color,
                  padding: '1px 6px',
                  borderRadius: 4,
                  fontSize: 9,
                  fontWeight: 600,
                  letterSpacing: '0.06em',
                  minWidth: 38,
                  textAlign: 'center',
                  flexShrink: 0,
                }}
              >
                {style.label}
              </span>
              <span style={{ color: '#c8d8e8', wordBreak: 'break-word' }}>{log.message}</span>
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <ToolButton
          icon={paused ? <Play size={14} /> : <Pause size={14} />}
          label={paused ? 'Resume' : 'Pause'}
          onClick={() => (paused ? handleResume() : setPaused(true))}
        />
        <ToolButton
          icon={<ArrowDown size={14} />}
          label="Auto-scroll"
          active={autoScroll}
          onClick={() => setAutoScroll(!autoScroll)}
        />
        <ToolButton icon={<Trash2 size={14} />} label="Clear" onClick={handleClear} />
        <ToolButton icon={<Download size={14} />} label="Export" onClick={handleExport} />
      </div>
    </div>
  );
}

function ToolButton({
  icon,
  label,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '6px 12px',
        borderRadius: 8,
        border: `1px solid ${active ? 'rgba(34, 211, 238, 0.3)' : 'rgba(255,255,255,0.06)'}`,
        background: active ? 'rgba(34, 211, 238, 0.08)' : 'transparent',
        color: active ? '#22d3ee' : '#7dd3fc',
        fontSize: 12,
        fontFamily: "'Inter', sans-serif",
        cursor: 'pointer',
        transition: 'all 0.2s',
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
