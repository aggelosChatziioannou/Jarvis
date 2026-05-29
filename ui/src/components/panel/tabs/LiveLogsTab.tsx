import { useEffect, useRef, useState, useCallback } from 'react';
import {
  Search,
  Pause,
  ArrowDown,
  Trash2,
  Download,
  Play,
  Copy,
  Check,
  Inbox,
  Zap,
  Film,
} from 'lucide-react';
import { api, openLogStream, type LogPayload } from '@/lib/api';

const LEVEL_STYLES: Record<string, { bg: string; color: string; label: string; border: string }> = {
  info: { bg: 'rgba(79, 209, 197, 0.06)', color: '#4fd1c5', label: 'INFO', border: 'rgba(79, 209, 197, 0.25)' },
  warning: { bg: 'rgba(246, 173, 85, 0.06)', color: '#f6ad55', label: 'WARN', border: 'rgba(246, 173, 85, 0.25)' },
  error: { bg: 'rgba(252, 129, 129, 0.06)', color: '#fc8181', label: 'ERROR', border: 'rgba(252, 129, 129, 0.25)' },
  'fast-path': { bg: 'rgba(167, 139, 250, 0.06)', color: '#a78bfa', label: 'FAST', border: 'rgba(167, 139, 250, 0.25)' },
  mcp: { bg: 'rgba(167, 139, 250, 0.06)', color: '#a78bfa', label: 'MCP', border: 'rgba(167, 139, 250, 0.25)' },
  'easter-egg': { bg: 'rgba(244, 114, 182, 0.06)', color: '#f472b6', label: 'EGG', border: 'rgba(244, 114, 182, 0.25)' },
};

const FILTER_CHIPS = [
  { key: 'info', label: 'Info', color: '#4fd1c5' },
  { key: 'warning', label: 'Warning', color: '#f6ad55' },
  { key: 'error', label: 'Error', color: '#fc8181' },
  { key: 'fast-path', label: 'Fast-path', color: '#a78bfa', Icon: Zap },
  { key: 'mcp', label: 'MCP', color: '#a78bfa' },
  { key: 'easter-egg', label: 'Easter Egg', color: '#f472b6', Icon: Film },
];

export default function LiveLogsTab() {
  const [logs, setLogs] = useState<LogPayload[]>([]);
  const [search, setSearch] = useState('');
  const [activeFilters, setActiveFilters] = useState<Set<string>>(
    new Set(['info', 'warning', 'error', 'fast-path', 'mcp', 'easter-egg'])
  );
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
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

  const handleCopy = useCallback((log: LogPayload) => {
    const text = `[${log.timestamp}] [${log.level.toUpperCase()}] ${log.message}`;
    navigator.clipboard.writeText(text).then(() => {
      setCopiedId(log.id);
      setTimeout(() => setCopiedId(null), 1500);
    });
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 16 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            background: 'rgba(8, 14, 28, 0.6)',
            border: '1px solid rgba(79, 209, 197, 0.12)',
            borderRadius: 8,
            padding: '0 14px',
            height: 40,
          }}
        >
          <Search size={16} color="#4a5568" />
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
          {search && (
            <span style={{ color: '#4a5568', fontSize: 11, fontFamily: "'Inter', sans-serif" }}>
              {filtered.length} result{filtered.length !== 1 ? 's' : ''}
            </span>
          )}
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
                  color: active ? chip.color : '#4a5568',
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
                {chip.Icon && <chip.Icon size={10} color={active ? chip.color : '#4a5568'} />}
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
          background: '#060a12',
          borderRadius: 4,
          border: '1px solid rgba(79, 209, 197, 0.06)',
          fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace",
          fontSize: 13,
          padding: '12px',
        }}
      >
        {filtered.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', color: '#4a5568', fontSize: 13 }}>
            <Inbox size={24} style={{ marginBottom: 8, opacity: 0.3 }} />
            Waiting for logs...
          </div>
        )}
        {filtered.map((log, index) => {
          const style = LEVEL_STYLES[log.level] || LEVEL_STYLES.info;
          const isHovered = hoveredId === log.id;
          return (
            <div
              key={log.id}
              onMouseEnter={() => setHoveredId(log.id)}
              onMouseLeave={() => setHoveredId(null)}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 10,
                padding: '8px 12px',
                marginBottom: 4,
                borderRadius: 6,
                borderLeft: `3px solid ${style.border}`,
                background: isHovered
                  ? 'rgba(255,255,255,0.04)'
                  : index % 2 === 0
                    ? 'rgba(255,255,255,0.015)'
                    : 'transparent',
                transition: 'background 0.15s',
                position: 'relative',
              }}
            >
              <span
                style={{
                  color: '#4a5568',
                  fontSize: 11,
                  minWidth: 80,
                  flexShrink: 0,
                  marginTop: 1,
                }}
              >
                {log.timestamp}
              </span>
              <span
                style={{
                  background: style.bg,
                  color: style.color,
                  padding: '2px 7px',
                  borderRadius: 4,
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: '0.06em',
                  minWidth: 38,
                  textAlign: 'center',
                  flexShrink: 0,
                  marginTop: 2,
                  border: `1px solid ${style.border}`,
                }}
              >
                {style.label}
              </span>
              <span
                style={{
                  color: '#a0aec0',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  lineHeight: '1.6',
                  flex: 1,
                  paddingRight: 24,
                }}
              >
                {log.message}
              </span>

              {isHovered && (
                <button
                  onClick={() => handleCopy(log)}
                  title="Copy log"
                  style={{
                    position: 'absolute',
                    right: 8,
                    top: 8,
                    background: 'rgba(8, 14, 28, 0.8)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: 6,
                    padding: 4,
                    cursor: 'pointer',
                    color: copiedId === log.id ? '#34d399' : '#4fd1c5',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    transition: 'all 0.2s',
                  }}
                >
                  {copiedId === log.id ? <Check size={12} /> : <Copy size={12} />}
                </button>
              )}
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
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

        <div
          style={{
            marginLeft: 'auto',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            color: '#4a5568',
            fontSize: 11,
            fontFamily: "'Inter', sans-serif",
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: paused ? '#f6ad55' : '#34d399',
              display: 'inline-block',
              boxShadow: paused
                ? '0 0 6px rgba(246, 173, 85, 0.4)'
                : '0 0 6px rgba(52, 211, 153, 0.4)',
            }}
          />
          {paused ? 'Paused' : 'Live'} · {filtered.length} shown
          {filtered.length !== logs.length && ` / ${logs.length} total`}
        </div>
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
        border: `1px solid ${active ? 'rgba(79, 209, 197, 0.3)' : 'rgba(255,255,255,0.06)'}`,
        background: active ? 'rgba(79, 209, 197, 0.08)' : 'transparent',
        color: active ? '#4fd1c5' : '#a0aec0',
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
