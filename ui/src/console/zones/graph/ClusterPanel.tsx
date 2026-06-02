import React, { memo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { GraphLayoutNode } from './useGraphLayout';
import type { CategoryType } from '@/console/types/graph';
import { memoryNodes, categories } from '@/console/data/graphMock';

const CategoryIcon = memo(function CategoryIcon({ category, size = 18 }: { category: CategoryType; size?: number }) {
  const icons: Record<string, React.ReactNode> = {
    identity: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2a5 5 0 0 1 5 5v2a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z" /><path d="M12 14v8" /><path d="M9 18h6" />
      </svg>
    ),
    preferences: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
      </svg>
    ),
    events: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
      </svg>
    ),
    directives: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="4 17 10 11 4 5" /><line x1="12" y1="19" x2="20" y2="19" />
      </svg>
    ),
    health: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    ),
  };
  return <>{icons[category] ?? null}</>;
});

const PencilIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
);

const XIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

// ── Inline Detail View (shows info) ──
function DetailCard({
  memNode,
  color,
  onEdit,
  onClose,
}: {
  memNode: GraphLayoutNode;
  color: string;
  onEdit: () => void;
  onClose: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
      className="overflow-hidden"
    >
      <div className="mx-2 px-3 py-3 rounded-lg border" style={{
        backgroundColor: 'rgba(10, 14, 23, 0.7)',
        borderColor: `${color}25`,
        boxShadow: `0 0 16px ${color}08, inset 0 0 20px rgba(0,0,0,0.3)`,
      }}>
        {/* Value */}
        <div className="mb-2.5">
          <label className="block text-[9px] text-[#475569] tracking-wider uppercase mb-1">Value</label>
          <div className="text-[12px] text-[#f8fafc] font-mono break-all">{memNode.value || '—'}</div>
        </div>
        {/* Importance */}
        <div className="mb-2">
          <div className="flex items-center justify-between mb-1">
            <label className="text-[9px] text-[#475569] tracking-wider uppercase">Importance</label>
            <span className="text-[10px] font-mono" style={{ color }}>{memNode.importance}/10</span>
          </div>
          <div className="flex gap-0.5">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="w-3 h-1.5 rounded-sm" style={{
                backgroundColor: i < memNode.importance ? color : 'rgba(255,255,255,0.04)',
              }} />
            ))}
          </div>
        </div>
        {/* Confidence */}
        <div className="mb-2.5 flex items-center justify-between">
          <label className="text-[9px] text-[#475569] tracking-wider uppercase">Confidence</label>
          <span className="text-[11px] font-mono text-[#94a3b8]">{memNode.confidence}%</span>
        </div>
        {/* Permanent */}
        <div className="mb-3 flex items-center justify-between">
          <label className="text-[9px] text-[#475569] tracking-wider uppercase">Permanent</label>
          <span className="text-[11px] font-mono" style={{ color: memNode.permanent ? '#34d399' : '#fb7185' }}>
            {memNode.permanent ? 'Yes' : 'No'}
          </span>
        </div>
        {/* Actions */}
        <div className="flex gap-2">
          <button
            onClick={onEdit}
            className="flex-1 h-7 rounded-md text-[11px] font-semibold flex items-center justify-center gap-1.5 transition-all duration-150 hover:opacity-80"
            style={{ backgroundColor: color, color: '#0a0e17' }}
          >
            <PencilIcon /> Edit
          </button>
          <button
            onClick={onClose}
            className="h-7 px-3 rounded-md text-[11px] text-[#475569] border border-white/5 hover:border-white/10 hover:text-[#94a3b8] transition-all duration-150 flex items-center justify-center gap-1"
          >
            <XIcon /> Close
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// ── Inline Editor ──
function EditorCard({
  memNode,
  color,
  onSave,
  onCancel,
}: {
  memNode: GraphLayoutNode;
  color: string;
  onSave: (id: string, value: string, importance: number, permanent: boolean) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(memNode.value ?? '');
  const [importance, setImportance] = useState(memNode.importance);
  const [permanent, setPermanent] = useState(memNode.permanent ?? true);

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
      className="overflow-hidden"
    >
      <div className="mx-2 px-3 py-3 rounded-lg border" style={{
        backgroundColor: 'rgba(10, 14, 23, 0.7)',
        borderColor: `${color}40`,
        boxShadow: `0 0 20px ${color}12, inset 0 0 20px rgba(0,0,0,0.3)`,
      }}>
        {/* Value */}
        <div className="mb-3">
          <label className="block text-[9px] text-[#475569] tracking-wider uppercase mb-1">Value</label>
          <input
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-full h-7 px-2.5 rounded-md bg-[#0a0e17] text-[12px] text-[#f8fafc] border border-white/5 outline-none transition-all duration-200 focus:border-[#22d3ee]/40"
          />
        </div>
        {/* Importance */}
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <label className="text-[9px] text-[#475569] tracking-wider uppercase">Importance</label>
            <span className="text-[10px] font-mono" style={{ color }}>{importance}/10</span>
          </div>
          <div className="flex gap-1">
            {Array.from({ length: 10 }).map((_, i) => (
              <button
                key={i}
                onClick={() => setImportance(i + 1)}
                className="w-5 h-6 rounded-sm transition-all duration-150 hover:opacity-80"
                style={{
                  backgroundColor: i < importance ? color : 'rgba(255,255,255,0.04)',
                  boxShadow: i < importance ? `0 0 6px ${color}40` : 'none',
                }}
              />
            ))}
          </div>
        </div>
        {/* Permanent */}
        <div className="mb-3 flex items-center justify-between">
          <label className="text-[9px] text-[#475569] tracking-wider uppercase">Permanent</label>
          <button
            onClick={() => setPermanent(!permanent)}
            className={`relative w-8 h-[18px] rounded-full border transition-colors duration-150 ${permanent ? 'border-[#22d3ee]' : 'border-[#475569]'}`}
            style={{ backgroundColor: permanent ? '#22d3ee' : '#1e293b' }}
          >
            <div className={`absolute top-[1px] w-[14px] h-[14px] rounded-full bg-white transition-transform duration-150 ${permanent ? 'translate-x-[16px]' : 'translate-x-[1px]'}`} />
          </button>
        </div>
        {/* Actions */}
        <div className="flex gap-2">
          <button
            onClick={() => { onSave(memNode.id, value, importance, permanent); onCancel(); }}
            className="flex-1 h-7 rounded-md text-[11px] font-semibold flex items-center justify-center gap-1.5 transition-all duration-150 hover:opacity-80"
            style={{ backgroundColor: color, color: '#0a0e17' }}
          >
            Save
          </button>
          <button
            onClick={onCancel}
            className="h-7 px-3 rounded-md text-[11px] text-[#475569] border border-white/5 hover:border-white/10 hover:text-[#94a3b8] transition-all duration-150 flex items-center justify-center gap-1"
          >
            <XIcon /> Cancel
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// ── Memory List Item ──
const MemoryListItem = memo(function MemoryListItem({
  memNode,
  color,
  isSelected,
  onSelect,
  index,
}: {
  memNode: GraphLayoutNode;
  color: string;
  isSelected: boolean;
  onSelect: () => void;
  index: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: 0.15 + index * 0.04, duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
    >
      <div
        onClick={onSelect}
        className={`group flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-all duration-200 ${
          isSelected ? 'bg-white/[0.06]' : 'hover:bg-white/[0.04]'
        }`}
        style={isSelected ? { borderLeft: `2px solid ${color}` } : undefined}
      >
        <div
          className="w-2 h-2 rounded-full shrink-0 transition-all duration-200 group-hover:scale-125"
          style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}60` }}
        />
        <div className="flex-1 min-w-0">
          <div className={`text-[12px] font-medium truncate transition-colors ${isSelected ? 'text-white' : 'text-[#f8fafc] group-hover:text-white'}`}>
            {memNode.label}
          </div>
          {memNode.value && (
            <div className="text-[10px] text-[#475569] font-mono truncate mt-0.5 group-hover:text-[#94a3b8] transition-colors">
              {memNode.value}
            </div>
          )}
        </div>
        <div
          className="text-[9px] font-mono px-1.5 py-0.5 rounded-full shrink-0"
          style={{ color, backgroundColor: `${color}15`, border: `1px solid ${color}30` }}
        >
          {memNode.confidence}%
        </div>
      </div>
    </motion.div>
  );
});

// ── Main Panel ──
export default function ClusterPanel({
  categoryNode,
  allNodes,
  onUpdateMemory,
  onClose,
}: {
  categoryNode: GraphLayoutNode | null;
  allNodes: GraphLayoutNode[];
  onUpdateMemory: (id: string, value: string, importance: number, permanent: boolean) => void;
  onClose: () => void;
}) {
  const [selectedMemId, setSelectedMemId] = useState<string | null>(null);
  const [editingMemId, setEditingMemId] = useState<string | null>(null);

  const isOpen = categoryNode !== null && categoryNode.type === 'category';
  const category = categories.find((c) => c.type === categoryNode?.category);
  const color = category?.color ?? '#22d3ee';
  const glow = category?.glow ?? 'rgba(34, 211, 238, 0.12)';

  const memories = React.useMemo(() => {
    if (!categoryNode) return [];
    return allNodes.filter((n) => n.type === 'memory' && n.category === categoryNode.category);
  }, [categoryNode, allNodes]);

  const avgConfidence = memories.length > 0 ? Math.round(memories.reduce((s, m) => s + m.confidence, 0) / memories.length) : 0;
  const highImportance = memories.filter((m) => m.importance >= 7).length;
  const recentChanges = memories.filter((m) => {
    const full = memoryNodes.find((fn) => fn.id === m.id);
    return full?.recentlyChanged;
  }).length;

  return (
    <AnimatePresence>
      {isOpen && categoryNode && (
        <motion.div
          initial={{ x: 300, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 300, opacity: 0 }}
          transition={{ type: 'spring', stiffness: 280, damping: 28, mass: 0.8 }}
          className="absolute top-0 right-0 bottom-0 z-30 flex flex-col"
          style={{ width: 270, pointerEvents: 'auto' }}
        >
          <div className="flex flex-col h-full m-2 ml-0 rounded-xl overflow-hidden" style={{
            backgroundColor: 'rgba(10, 14, 23, 0.92)',
            border: '1px solid rgba(255, 255, 255, 0.06)',
            borderTop: `2px solid ${color}`,
            boxShadow: `0 0 30px ${glow}, 0 8px 32px rgba(0, 0, 0, 0.4)`,
            backdropFilter: 'blur(12px)',
          }}>
            {/* Header */}
            <div className="relative px-4 pt-4 pb-3">
              <button onClick={onClose}
                className="absolute top-3 right-3 w-6 h-6 rounded-md flex items-center justify-center text-[#475569] hover:text-[#f8fafc] hover:bg-white/5 transition-all">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                  <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{
                  backgroundColor: `${color}15`, border: `1px solid ${color}30`, boxShadow: `0 0 12px ${color}20`,
                }}>
                  <span style={{ color }}><CategoryIcon category={categoryNode.category} size={18} /></span>
                </div>
                <div>
                  <h3 className="text-[14px] font-semibold text-[#f8fafc] tracking-wide">{categoryNode.label}</h3>
                  <p className="text-[10px] text-[#475569] font-mono tracking-wider uppercase mt-0.5">Cluster Overview</p>
                </div>
              </div>
            </div>

            {/* Stats */}
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08, duration: 0.25 }}
              className="grid grid-cols-3 gap-2 px-4 pb-3">
              {[
                { label: 'Memories', value: memories.length },
                { label: 'High Priority', value: highImportance, color },
                { label: 'Changes', value: recentChanges },
              ].map((stat, i) => (
                <div key={i} className="text-center py-2 rounded-lg"
                  style={{ backgroundColor: 'rgba(255, 255, 255, 0.02)', border: '1px solid rgba(255, 255, 255, 0.04)' }}>
                  <div className="text-[13px] font-semibold font-mono" style={{ color: stat.color ?? '#f8fafc' }}>{stat.value}</div>
                  <div className="text-[9px] text-[#475569] mt-0.5 tracking-wider uppercase">{stat.label}</div>
                </div>
              ))}
            </motion.div>

            {/* Confidence bar */}
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.12, duration: 0.25 }} className="px-4 pb-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[10px] text-[#475569] tracking-wider uppercase">Avg Confidence</span>
                <span className="text-[10px] font-mono" style={{ color }}>{avgConfidence}%</span>
              </div>
              <div className="w-full h-1 rounded-full overflow-hidden" style={{ backgroundColor: 'rgba(255, 255, 255, 0.04)' }}>
                <motion.div initial={{ width: 0 }} animate={{ width: `${avgConfidence}%` }} transition={{ delay: 0.2, duration: 0.6, ease: [0.25, 0.1, 0.25, 1] }}
                  className="h-full rounded-full" style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}60` }} />
              </div>
            </motion.div>

            <div className="mx-4 border-t border-white/5" />

            {/* List header */}
            <div className="px-4 pt-3 pb-1">
              <span className="text-[10px] text-[#475569] tracking-wider uppercase font-medium">Memory Nodes</span>
            </div>

            {/* Memory nodes list */}
            <div className="flex-1 overflow-y-auto px-2 py-1">
              {memories.map((mem, i) => (
                <div key={mem.id}>
                  <MemoryListItem
                    memNode={mem}
                    color={color}
                    isSelected={selectedMemId === mem.id}
                    index={i}
                    onSelect={() => {
                      if (selectedMemId === mem.id && editingMemId !== mem.id) {
                        setSelectedMemId(null);
                        setEditingMemId(null);
                      } else {
                        setSelectedMemId(mem.id);
                        setEditingMemId(null);
                      }
                    }}
                  />
                  {/* Expandable detail / editor */}
                  <AnimatePresence>
                    {selectedMemId === mem.id && editingMemId !== mem.id && (
                      <DetailCard
                        memNode={mem}
                        color={color}
                        onEdit={() => setEditingMemId(mem.id)}
                        onClose={() => { setSelectedMemId(null); setEditingMemId(null); }}
                      />
                    )}
                    {editingMemId === mem.id && (
                      <EditorCard
                        memNode={mem}
                        color={color}
                        onSave={(id, value, importance, permanent) => {
                          onUpdateMemory(id, value, importance, permanent);
                          setEditingMemId(null);
                        }}
                        onCancel={() => setEditingMemId(null)}
                      />
                    )}
                  </AnimatePresence>
                </div>
              ))}
            </div>

            <div className="absolute bottom-0 left-0 right-0 h-8 pointer-events-none rounded-b-xl"
              style={{ background: `linear-gradient(to top, ${color}08, transparent)` }} />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
