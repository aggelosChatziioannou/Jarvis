import React, { memo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { GraphLayoutNode } from './useGraphLayout';
import type { CategoryType } from '@/console/types/graph';
import { categories } from '@/console/data/graphMock';

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

const XIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

const PencilIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
);

const TrashIcon = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
  </svg>
);

// One fact row: click to reveal the full text + real Edit / Delete actions.
const FactRow = memo(function FactRow({
  fact, color, isOpen, index, onToggle, onSave, onDelete,
}: {
  fact: GraphLayoutNode;
  color: string;
  isOpen: boolean;
  index: number;
  onToggle: () => void;
  onSave: (id: string, value: string) => void;
  onDelete: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(fact.value ?? '');
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: 0.1 + index * 0.04, duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
    >
      <div
        onClick={onToggle}
        className={`group flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-pointer transition-all duration-200 ${
          isOpen ? 'bg-white/[0.06]' : 'hover:bg-white/[0.04]'
        }`}
        style={isOpen ? { borderLeft: `2px solid ${color}` } : undefined}
      >
        <div className="w-1.5 h-1.5 rounded-full shrink-0 transition-all duration-200 group-hover:scale-150"
          style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}60` }} />
        <div className="flex-1 min-w-0 text-[11.5px] text-[#cbd5e1] group-hover:text-white transition-colors truncate">
          {fact.value || fact.label}
        </div>
      </div>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease: [0.25, 0.1, 0.25, 1] }}
            className="overflow-hidden"
          >
            <div className="mx-2 mt-1 mb-2 px-3 py-2.5 rounded-lg border"
              style={{ backgroundColor: 'rgba(10, 14, 23, 0.7)', borderColor: `${color}25`, boxShadow: `0 0 14px ${color}08` }}>
              {editing ? (
                <>
                  <textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    rows={3}
                    autoFocus
                    className="w-full px-2.5 py-2 rounded-md bg-[#0a0e17] text-[11.5px] text-[#f8fafc] border border-white/10 outline-none transition-all duration-200 focus:border-[#22d3ee]/40 resize-none font-mono"
                  />
                  <div className="flex gap-2 mt-2">
                    <button
                      onClick={() => { onSave(fact.id, draft); setEditing(false); }}
                      className="flex-1 h-7 rounded-md text-[11px] font-semibold transition-all duration-150 hover:opacity-80"
                      style={{ backgroundColor: color, color: '#0a0e17' }}>
                      Save
                    </button>
                    <button onClick={() => { setEditing(false); setDraft(fact.value ?? ''); }}
                      className="h-7 px-3 rounded-md text-[11px] text-[#64748b] border border-white/5 hover:text-[#94a3b8] transition-all">
                      Cancel
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <div className="text-[11.5px] text-[#f8fafc] leading-relaxed break-words font-mono">{fact.value}</div>
                  <div className="flex gap-2 mt-2.5">
                    <button
                      onClick={() => { setDraft(fact.value ?? ''); setEditing(true); }}
                      className="flex-1 h-7 rounded-md text-[11px] font-semibold flex items-center justify-center gap-1.5 transition-all duration-150 hover:opacity-80"
                      style={{ backgroundColor: `${color}22`, color, border: `1px solid ${color}40` }}>
                      <PencilIcon /> Edit
                    </button>
                    {confirmDelete ? (
                      <button
                        onClick={() => onDelete(fact.id)}
                        className="flex-1 h-7 rounded-md text-[11px] font-semibold flex items-center justify-center gap-1.5 bg-[#ef4444] text-white transition-all duration-150 hover:opacity-80">
                        <TrashIcon /> Confirm
                      </button>
                    ) : (
                      <button
                        onClick={() => setConfirmDelete(true)}
                        className="h-7 px-3 rounded-md text-[11px] text-[#fb7185] border border-[#fb7185]/30 hover:bg-[#fb7185]/10 transition-all flex items-center gap-1.5">
                        <TrashIcon /> Forget
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
});

// ── Main Panel — overview + REAL per-fact edit/delete for a hub or cluster ──
export default function ClusterPanel({
  categoryNode,
  allNodes,
  onSaveMemory,
  onDeleteMemory,
  onClose,
}: {
  categoryNode: GraphLayoutNode | null;
  allNodes: GraphLayoutNode[];
  onSaveMemory: (id: string, value: string) => void;
  onDeleteMemory: (id: string) => void;
  onClose: () => void;
}) {
  const [openFactId, setOpenFactId] = useState<string | null>(null);

  const isOpen = categoryNode !== null && (categoryNode.type === 'category' || categoryNode.type === 'cluster');
  const category = categories.find((c) => c.type === categoryNode?.category);
  const color = category?.color ?? '#22d3ee';
  const glow = category?.glow ?? 'rgba(34, 211, 238, 0.12)';

  // Hub: every fact in the branch. Cluster: only its own facts.
  const facts = React.useMemo(() => {
    if (!categoryNode) return [];
    if (categoryNode.type === 'cluster') {
      return allNodes.filter((n) => n.type === 'memory' && n.parentId === categoryNode.id);
    }
    return allNodes.filter((n) => n.type === 'memory' && n.category === categoryNode.category);
  }, [categoryNode, allNodes]);

  const subClusters = React.useMemo(() => {
    if (!categoryNode || categoryNode.type !== 'category') return 0;
    return allNodes.filter((n) => n.type === 'cluster' && n.parentId === categoryNode.id).length;
  }, [categoryNode, allNodes]);

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
          onClick={(e) => e.stopPropagation()}
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
                <XIcon />
              </button>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{
                  backgroundColor: `${color}15`, border: `1px solid ${color}30`, boxShadow: `0 0 12px ${color}20`,
                }}>
                  <span style={{ color }}><CategoryIcon category={categoryNode.category} size={18} /></span>
                </div>
                <div>
                  <h3 className="text-[14px] font-semibold text-[#f8fafc] tracking-wide">{categoryNode.label}</h3>
                  <p className="text-[10px] text-[#475569] font-mono tracking-wider uppercase mt-0.5">
                    {categoryNode.type === 'cluster' ? 'Cluster' : 'Branch'} · {facts.length} {facts.length === 1 ? 'fact' : 'facts'}
                    {subClusters > 0 ? ` · ${subClusters} clusters` : ''}
                  </p>
                </div>
              </div>
              {/* Cluster description = the routing hint Jarvis itself uses */}
              {categoryNode.value && (
                <p className="mt-2.5 text-[10.5px] leading-relaxed text-[#64748b]">{categoryNode.value}</p>
              )}
            </div>

            <div className="mx-4 border-t border-white/5" />

            <div className="px-4 pt-3 pb-1 flex items-center justify-between">
              <span className="text-[10px] text-[#475569] tracking-wider uppercase font-medium">Stored facts</span>
              <span className="text-[10px] font-mono" style={{ color }}>{facts.length}</span>
            </div>

            {/* Facts list — click a row for full text + Edit / Forget */}
            <div className="flex-1 overflow-y-auto px-2 py-1">
              {facts.length === 0 && (
                <p className="px-3 py-4 text-[11px] text-[#475569]">
                  Nothing stored here yet — Jarvis files new facts automatically as you talk.
                </p>
              )}
              {facts.map((fact, i) => (
                <FactRow key={fact.id} fact={fact} color={color} index={i}
                  isOpen={openFactId === fact.id}
                  onToggle={() => setOpenFactId(openFactId === fact.id ? null : fact.id)}
                  onSave={onSaveMemory}
                  onDelete={(id) => { setOpenFactId(null); onDeleteMemory(id); }} />
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
