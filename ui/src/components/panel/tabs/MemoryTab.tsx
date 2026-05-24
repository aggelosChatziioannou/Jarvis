import { useEffect, useState } from 'react';
import { Search, Trash2, AlertTriangle } from 'lucide-react';
import { api, type MemoryItem } from '@/lib/api';

export default function MemoryTab() {
  const [search, setSearch] = useState('');
  const [showConfirm, setShowConfirm] = useState(false);
  const [memories, setMemories] = useState<MemoryItem[]>([]);

  useEffect(() => {
    api.memory().then(setMemories).catch(() => setMemories([]));
  }, []);

  useEffect(() => {
    const id = setTimeout(() => {
      api.memory(search || undefined).then(setMemories).catch(() => {});
    }, 250);
    return () => clearTimeout(id);
  }, [search]);

  const clearAll = async () => {
    await api.clearMemory().catch(() => {});
    setMemories([]);
    setShowConfirm(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 700 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <div
          style={{
            flex: 1,
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
            placeholder="Search memory..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: '#e6f1ff',
              fontSize: 13,
            }}
          />
        </div>
        <button
          onClick={() => setShowConfirm(true)}
          disabled={memories.length === 0}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '0 16px',
            height: 40,
            borderRadius: 10,
            border: '1px solid rgba(248, 113, 113, 0.2)',
            background: 'rgba(248, 113, 113, 0.05)',
            color: '#f87171',
            fontSize: 12,
            cursor: memories.length === 0 ? 'not-allowed' : 'pointer',
            opacity: memories.length === 0 ? 0.4 : 1,
          }}
        >
          <Trash2 size={14} />
          Clear All
        </button>
      </div>

      {showConfirm && (
        <div
          style={{
            background: 'rgba(248, 113, 113, 0.08)',
            border: '1px solid rgba(248, 113, 113, 0.2)',
            borderRadius: 10,
            padding: 16,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <AlertTriangle size={18} color="#f87171" />
          <div style={{ flex: 1 }}>
            <p style={{ color: '#e6f1ff', fontSize: 13, margin: 0 }}>
              Delete all {memories.length} memory entries?
            </p>
            <p style={{ color: '#5A7182', fontSize: 11, margin: '4px 0 0' }}>
              This action cannot be undone.
            </p>
          </div>
          <button
            onClick={clearAll}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: '1px solid rgba(248, 113, 113, 0.3)',
              background: 'rgba(248, 113, 113, 0.1)',
              color: '#f87171',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            Delete
          </button>
          <button
            onClick={() => setShowConfirm(false)}
            style={{
              padding: '6px 14px',
              borderRadius: 6,
              border: '1px solid rgba(255,255,255,0.1)',
              background: 'transparent',
              color: '#7dd3fc',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            Cancel
          </button>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {memories.map((entry) => (
          <div
            key={entry.id}
            style={{
              background: 'rgba(8, 14, 28, 0.4)',
              border: '1px solid rgba(34, 211, 238, 0.06)',
              borderRadius: 10,
              padding: '12px 16px',
            }}
          >
            <div style={{ fontSize: 10, color: '#5A7182', fontFamily: 'monospace', marginBottom: 4 }}>
              {entry.timestamp}
            </div>
            <div style={{ fontSize: 13, color: '#c8d8e8', lineHeight: 1.5 }}>{entry.snippet}</div>
          </div>
        ))}
        {memories.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: '#5A7182', fontSize: 13 }}>
            No memory entries found.
          </div>
        )}
      </div>
    </div>
  );
}
