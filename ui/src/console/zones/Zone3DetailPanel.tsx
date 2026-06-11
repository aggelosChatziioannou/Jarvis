import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronLeft, ChevronRight, Brain, Save, Trash2, Clock, BellOff } from 'lucide-react';
import Card from '@/console/components/Card';
import Badge from '@/console/components/Badge';
import { useMemoryDataCtx } from '@/console/services/MemoryDataContext';
import type { GraphNode, Reminder } from '@/console/types';

interface Props {
  selectedNode: GraphNode | null;
  selectedReminder: Reminder | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNodeSelect: (node: GraphNode | null) => void;
  onReminderSelect: (r: Reminder | null) => void;
}

function NodeEditor({ node, onNodeSelect }: { node: GraphNode; onNodeSelect: (node: GraphNode | null) => void }) {
  const { fetchNodeData, saveNodeData, deleteNode } = useMemoryDataCtx();
  const [value, setValue] = useState(node.value || '');
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  // Pull the node's real facts (data) for editing; falls back to the summary value.
  useEffect(() => {
    let alive = true;
    fetchNodeData(node.id).then((data) => {
      if (alive && data) setValue(data);
    }).catch(() => {});
    return () => { alive = false; };
  }, [node.id, fetchNodeData]);

  const handleSave = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await saveNodeData(node.id, value);
      setSaved(true);
      setTimeout(() => setSaved(false), 600);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await deleteNode(node.id);
      onNodeSelect(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-4 space-y-4">
      <div>
        <Badge category={node.category}>{node.category}</Badge>
        <h3 className="text-[15px] font-semibold text-[#f8fafc] mt-2">{node.label}</h3>
      </div>

      <div className="space-y-3">
        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">
            Content
          </label>
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={6}
            className={`w-full px-3 py-2 rounded-lg bg-[#1e293b] text-[#f8fafc] text-[13px] border border-transparent focus:border-[#22d3ee] focus:outline-none focus:ring-1 focus:ring-[#22d3ee]/30 transition-all duration-150 resize-none ${saved ? 'animate-cyan-flash' : ''}`}
          />
          <p className="text-[10px] text-[#475569] mt-1">The node's stored facts (one per line).</p>
        </div>

        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">
            Confidence
          </label>
          <Badge category={node.category} variant="outline">
            {Math.round(node.confidence * 100)}%
          </Badge>
        </div>
      </div>

      <div className="flex gap-2 pt-2">
        <button
          onClick={() => void handleSave()}
          disabled={busy}
          className="flex-1 h-8 flex items-center justify-center gap-1.5 rounded-lg bg-[#22d3ee] text-[#0a0e17] text-[12px] font-semibold hover:bg-[#22d3ee]/80 transition-colors disabled:opacity-50"
        >
          <Save size={13} /> Save
        </button>
        <button
          onClick={() => void handleDelete()}
          disabled={busy}
          title="Delete this memory node"
          className="h-8 px-3 flex items-center justify-center rounded-lg border border-[#fb7185]/40 text-[#fb7185] hover:bg-[#fb7185]/10 transition-colors disabled:opacity-50"
        >
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  );
}

function ReminderEditor({ reminder, onReminderSelect }: { reminder: Reminder; onReminderSelect: (r: Reminder | null) => void }) {
  const { rescheduleReminder, setReminderStatus, snoozeReminder, deleteReminder } = useMemoryDataCtx();
  const [time, setTime] = useState(reminder.time || '12:00');
  const [date, setDate] = useState(reminder.date || '');
  const [status, setStatus] = useState(reminder.status);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      setSaved(true);
      setTimeout(() => setSaved(false), 600);
    } finally {
      setBusy(false);
    }
  };

  const handleSave = () =>
    run(async () => {
      if (status === 'completed' || status === 'cancelled') {
        await setReminderStatus(reminder.id, status);
      } else if (date) {
        await rescheduleReminder(reminder.id, date, time);
      }
      onReminderSelect(null);
    });

  return (
    <div className="p-4 space-y-4">
      <div>
        <Badge category={reminder.category || 'Events'}>Reminder</Badge>
        <h3 className={`text-[15px] font-semibold text-[#f8fafc] mt-2 ${saved ? 'animate-cyan-flash' : ''}`}>{reminder.title}</h3>
      </div>

      <div className="space-y-3">
        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">Time</label>
          <div className="flex items-center gap-2">
            <Clock size={13} className="text-[#475569]" />
            <input
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="flex-1 h-8 px-2 rounded-lg bg-[#1e293b] text-[#f8fafc] text-[13px] border border-transparent focus:border-[#22d3ee] focus:outline-none"
            />
          </div>
        </div>

        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">Date</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-full h-8 px-2 rounded-lg bg-[#1e293b] text-[#f8fafc] text-[13px] border border-transparent focus:border-[#22d3ee] focus:outline-none"
          />
        </div>

        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as Reminder['status'])}
            className="w-full h-8 px-2 rounded-lg bg-[#1e293b] text-[#f8fafc] text-[13px] border border-transparent focus:border-[#22d3ee] focus:outline-none appearance-none cursor-pointer"
          >
            <option value="pending">Pending (reschedule)</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
      </div>

      <div className="flex gap-2 pt-2">
        <button
          onClick={handleSave}
          disabled={busy}
          className="flex-1 h-8 flex items-center justify-center gap-1.5 rounded-lg bg-[#22d3ee] text-[#0a0e17] text-[12px] font-semibold hover:bg-[#22d3ee]/80 transition-colors disabled:opacity-50"
        >
          <Save size={13} /> Save
        </button>
        <button
          onClick={() => void run(async () => { await deleteReminder(reminder.id); onReminderSelect(null); })}
          disabled={busy}
          title="Delete reminder"
          className="h-8 px-3 flex items-center justify-center rounded-lg border border-[#fb7185]/40 text-[#fb7185] hover:bg-[#fb7185]/10 transition-colors disabled:opacity-50"
        >
          <Trash2 size={13} />
        </button>
        <button
          onClick={() => void run(async () => { await snoozeReminder(reminder.id); onReminderSelect(null); })}
          disabled={busy}
          title="Snooze 10 min"
          className="h-8 px-3 flex items-center justify-center rounded-lg border border-white/10 text-[#475569] hover:text-[#fbbf24] hover:border-white/20 transition-colors disabled:opacity-50"
        >
          <BellOff size={13} />
        </button>
      </div>
    </div>
  );
}

function EmptyInspector() {
  const { reminders, graphNodes } = useMemoryDataCtx();
  const facts = graphNodes.filter((n) => n.type === 'memory').length;
  const pending = reminders.filter((r) => r.status === 'pending' || r.status === 'snoozed').length;
  const stats = [
    { label: 'Facts', value: facts },
    { label: 'Reminders', value: pending },
    { label: 'Total', value: facts + reminders.length },
  ];
  return (
    <div className="h-full flex flex-col items-center justify-center p-6 text-center relative">
      <div className="relative mb-6">
        <div className="w-20 h-20 rounded-full border border-[#22d3ee]/10 animate-glow-pulse" />
        <div className="absolute inset-2 rounded-full border border-[#22d3ee]/20" style={{ animation: 'glow-pulse 3s ease-in-out infinite reverse' }} />
        <div className="absolute inset-5 rounded-full border border-[#22d3ee]/30 flex items-center justify-center">
          <Brain size={22} className="text-[#22d3ee]/40" strokeWidth={1.5} />
        </div>
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: '8s' }}>
          <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1 w-1.5 h-1.5 rounded-full bg-[#22d3ee]" style={{ boxShadow: '0 0 6px #22d3ee' }} />
        </div>
      </div>
      <p className="text-[#94a3b8] text-[13px] mb-1">Select a node or event to inspect</p>
      <p className="text-[#475569] text-[11px] mb-4">Click any memory on the graph</p>
      <div className="flex items-center gap-4 px-4 py-2 rounded-lg border border-white/5" style={{ backgroundColor: 'rgba(15, 23, 42, 0.4)' }}>
        {stats.map((s) => (
          <div key={s.label} className="text-center">
            <div className="text-[13px] font-semibold font-mono text-[#22d3ee]">{s.value}</div>
            <div className="text-[9px] text-[#475569] tracking-wider uppercase">{s.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Zone3DetailPanel({
  selectedNode,
  selectedReminder,
  collapsed,
  onToggleCollapse,
  onNodeSelect,
  onReminderSelect,
}: Props) {
  return (
    <Card className="h-full relative flex flex-col" noPadding>
      <button
        onClick={onToggleCollapse}
        className="absolute left-0 top-1/2 -translate-x-1/2 z-10 w-5 h-10 flex items-center justify-center rounded-full bg-[#1e293b] border border-white/10 text-[#475569] hover:text-[#94a3b8] hover:border-white/20 transition-all duration-150"
      >
        {collapsed ? <ChevronLeft size={12} /> : <ChevronRight size={12} />}
      </button>

      <AnimatePresence mode="wait">
        {collapsed ? (
          <motion.div key="collapsed" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full flex flex-col items-center justify-center gap-4 py-4">
            <Brain size={20} className="text-[#475569]" />
          </motion.div>
        ) : (
          <motion.div key="expanded" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} className="h-full overflow-y-auto">
            <AnimatePresence mode="wait">
              {selectedNode ? (
                <motion.div key={`node-${selectedNode.id}`} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} transition={{ duration: 0.2 }}>
                  <NodeEditor node={selectedNode} onNodeSelect={onNodeSelect} />
                </motion.div>
              ) : selectedReminder ? (
                <motion.div key={`reminder-${selectedReminder.id}`} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} transition={{ duration: 0.2 }}>
                  <ReminderEditor reminder={selectedReminder} onReminderSelect={onReminderSelect} />
                </motion.div>
              ) : (
                <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  <EmptyInspector />
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
