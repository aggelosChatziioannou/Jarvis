import { useEffect, useState } from 'react';
import { Zap } from 'lucide-react';
import { api, type FastPathInfo } from '@/lib/api';

export default function FastPathsTab() {
  const [paths, setPaths] = useState<FastPathInfo[]>([]);

  useEffect(() => {
    api.fastpaths().then(setPaths).catch(() => setPaths([]));
  }, []);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
        <Zap size={16} color="#22d3ee" />
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: '#7dd3fc',
          }}
        >
          Fast Path Registry
        </span>
        <span style={{ fontSize: 11, color: '#5A7182', marginLeft: 8 }}>
          {paths.length} patterns
        </span>
      </div>

      <div
        style={{
          overflow: 'auto',
          borderRadius: 10,
          border: '1px solid rgba(34, 211, 238, 0.08)',
          maxHeight: 560,
        }}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1.5fr 1.5fr 2fr',
            gap: 0,
            background: 'rgba(8, 14, 28, 0.6)',
            padding: '10px 16px',
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            color: '#5A7182',
            borderBottom: '1px solid rgba(34, 211, 238, 0.08)',
            position: 'sticky',
            top: 0,
          }}
        >
          <div>Trigger Pattern</div>
          <div>Tool Chain</div>
          <div>Response Template</div>
        </div>

        {paths.map((fp, i) => (
          <div
            key={fp.id}
            style={{
              display: 'grid',
              gridTemplateColumns: '1.5fr 1.5fr 2fr',
              gap: 0,
              padding: '10px 16px',
              fontSize: 12,
              background: i % 2 === 0 ? 'rgba(8, 14, 28, 0.3)' : 'transparent',
              borderBottom: '1px solid rgba(255,255,255,0.02)',
              alignItems: 'center',
            }}
          >
            <div style={{ color: '#22d3ee', fontFamily: "'JetBrains Mono', monospace", fontSize: 11, wordBreak: 'break-all' }}>
              {fp.pattern || '—'}
            </div>
            <div style={{ color: '#a78bfa', fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
              {fp.tool || '—'}
            </div>
            <div style={{ color: '#c8d8e8' }}>{fp.response || '(action only)'}</div>
          </div>
        ))}

        {paths.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', color: '#5A7182', fontSize: 13 }}>
            No fast-path patterns registered.
          </div>
        )}
      </div>

      <p style={{ color: '#5A7182', fontSize: 11, marginTop: 12 }}>
        Fast paths bypass LLM inference for common commands, reducing latency to under 200 ms.
      </p>
    </div>
  );
}
