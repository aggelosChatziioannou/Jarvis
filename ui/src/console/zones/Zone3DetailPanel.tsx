import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronLeft, ChevronRight, Brain, Save, Trash2, History, Clock, BellOff } from 'lucide-react';
import Card from '@/console/components/Card';
import Badge from '@/console/components/Badge';
import ToggleSwitch from '@/console/components/ToggleSwitch';
import { sampleHistory } from '@/console/data/demo';
import type { GraphNode, Reminder } from '@/console/types';
import { CATEGORY_COLORS } from '@/console/types';

interface Props {
  selectedNode: GraphNode | null;
  selectedReminder: Reminder | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNodeSelect: (node: GraphNode | null) => void;
}

function NodeEditor({ node, onNodeSelect }: { node: GraphNode; onNodeSelect: (node: GraphNode | null) => void }) {
  const [value, setValue] = useState(node.value || '');
  const [importance, setImportance] = useState(node.importance);
  const [permanent, setPermanent] = useState(node.permanent);
  const [showHistory, setShowHistory] = useState(false);
  const [saved, setSaved] = useState(false);

  const history = sampleHistory.find((h) => h.nodeId === node.id);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 600);
  };

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div>
        <Badge category={node.category}>{node.category}</Badge>
        <h3 className="text-[15px] font-semibold text-[#f8fafc] mt-2">{node.label}</h3>
      </div>

      {/* Fields */}
      <div className="space-y-3">
        {/* Value */}
        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">
            Value
          </label>
          <input
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className={`
              w-full h-8 px-3 rounded-lg bg-[#1e293b] text-[#f8fafc] text-[13px]
              border border-transparent focus:border-[#22d3ee] focus:outline-none focus:ring-1 focus:ring-[#22d3ee]/30
              transition-all duration-150
              ${saved ? 'animate-cyan-flash' : ''}
            `}
          />
        </div>

        {/* Importance slider */}
        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block flex justify-between">
            <span>Importance</span>
            <span className="text-[#22d3ee]">{Math.round(importance * 100)}%</span>
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={importance}
            onChange={(e) => setImportance(parseFloat(e.target.value))}
            className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
            style={{
              background: `linear-gradient(to right, #22d3ee ${importance * 100}%, #334155 ${importance * 100}%)`,
            }}
          />
        </div>

        {/* Confidence */}
        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">
            Confidence
          </label>
          <Badge category={node.category} variant="outline">
            {Math.round(node.confidence * 100)}%
          </Badge>
        </div>

        {/* Permanent toggle */}
        <div>
          <ToggleSwitch checked={permanent} onChange={setPermanent} label="Permanent" />
        </div>

        {/* TTL */}
        {!permanent && (
          <div>
            <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">
              TTL
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                defaultValue={node.ttl || 30}
                className="w-16 h-8 px-2 rounded-lg bg-[#1e293b] text-[#f8fafc] text-[13px] border border-transparent focus:border-[#22d3ee] focus:outline-none"
              />
              <span className="text-[12px] text-[#94a3b8]">days</span>
            </div>
          </div>
        )}
        {permanent && (
          <div>
            <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">
              TTL
            </label>
            <span className="text-[13px] text-[#475569]">&infin;</span>
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex gap-2 pt-2">
        <button
          onClick={handleSave}
          className="flex-1 h-8 flex items-center justify-center gap-1.5 rounded-lg bg-[#22d3ee] text-[#0a0e17] text-[12px] font-semibold hover:bg-[#22d3ee]/80 transition-colors"
        >
          <Save size={13} />
          Save
        </button>
        <button
          onClick={() => onNodeSelect(null)}
          className="h-8 px-3 flex items-center justify-center rounded-lg border border-[#fb7185]/40 text-[#fb7185] hover:bg-[#fb7185]/10 transition-colors"
        >
          <Trash2 size={13} />
        </button>
        {history && (
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="h-8 px-3 flex items-center justify-center rounded-lg border border-white/10 text-[#475569] hover:text-[#94a3b8] hover:border-white/20 transition-colors"
          >
            <History size={13} />
          </button>
        )}
      </div>

      {/* History chain */}
      <AnimatePresence>
        {showHistory && history && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pt-2 border-t border-white/5">
              <h4 className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-2">
                History
              </h4>
              <div className="relative pl-3">
                {/* Vertical line */}
                <div className="absolute left-[5px] top-1 bottom-1 w-px bg-white/10" />

                {history.versions.map((ver, i) => (
                  <div key={i} className="relative mb-3 last:mb-0">
                    {/* Dot */}
                    <div
                      className="absolute left-[-7px] top-1 w-[9px] h-[9px] rounded-full border-2"
                      style={{
                        borderColor: CATEGORY_COLORS[node.category],
                        backgroundColor: i === history.versions.length - 1 ? CATEGORY_COLORS[node.category] : '#0a0e17',
                      }}
                    />
                    <div className="text-[11px] text-[#f8fafc] font-medium">{ver.value}</div>
                    <div className="text-[10px] text-[#475569] font-mono">{ver.timestamp}</div>
                    {ver.reason && (
                      <div className="text-[10px] text-[#94a3b8]">{ver.reason}</div>
                    )}
                    {i < history.versions.length - 1 && (
                      <div className="text-[10px] text-[#22d3ee] mt-0.5">&darr;</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ReminderEditor({ reminder, onReminderSelect }: { reminder: Reminder; onReminderSelect: (r: Reminder | null) => void }) {
  const [title, setTitle] = useState(reminder.title);
  const [status, setStatus] = useState(reminder.status);
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 600);
  };

  return (
    <div className="p-4 space-y-4">
      <div>
        <Badge category={reminder.category || 'Events'}>Reminder</Badge>
        <h3 className="text-[15px] font-semibold text-[#f8fafc] mt-2">Edit Reminder</h3>
      </div>

      <div className="space-y-3">
        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">
            Title
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={`
              w-full h-8 px-3 rounded-lg bg-[#1e293b] text-[#f8fafc] text-[13px]
              border border-transparent focus:border-[#22d3ee] focus:outline-none focus:ring-1 focus:ring-[#22d3ee]/30
              transition-all duration-150
              ${saved ? 'animate-cyan-flash' : ''}
            `}
          />
        </div>

        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">
            Time
          </label>
          <div className="flex items-center gap-2">
            <Clock size={13} className="text-[#475569]" />
            <input
              type="time"
              defaultValue={reminder.time}
              className="flex-1 h-8 px-2 rounded-lg bg-[#1e293b] text-[#f8fafc] text-[13px] border border-transparent focus:border-[#22d3ee] focus:outline-none"
            />
          </div>
        </div>

        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">
            Date
          </label>
          <input
            type="date"
            defaultValue={reminder.date}
            className="w-full h-8 px-2 rounded-lg bg-[#1e293b] text-[#f8fafc] text-[13px] border border-transparent focus:border-[#22d3ee] focus:outline-none"
          />
        </div>

        <div>
          <ToggleSwitch
            checked={!!reminder.recurring}
            onChange={() => {}}
            label={reminder.recurring ? 'Recurring • Every day' : 'One-time'}
          />
        </div>

        <div>
          <label className="text-[11px] text-[#94a3b8] uppercase tracking-wider font-medium mb-1 block">
            Status
          </label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as Reminder['status'])}
            className="w-full h-8 px-2 rounded-lg bg-[#1e293b] text-[#f8fafc] text-[13px] border border-transparent focus:border-[#22d3ee] focus:outline-none appearance-none cursor-pointer"
          >
            <option value="pending">Pending</option>
            <option value="completed">Completed</option>
            <option value="snoozed">Snoozed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
      </div>

      <div className="flex gap-2 pt-2">
        <button
          onClick={handleSave}
          className="flex-1 h-8 flex items-center justify-center gap-1.5 rounded-lg bg-[#22d3ee] text-[#0a0e17] text-[12px] font-semibold hover:bg-[#22d3ee]/80 transition-colors"
        >
          <Save size={13} />
          Save
        </button>
        <button
          onClick={() => onReminderSelect(null)}
          className="h-8 px-3 flex items-center justify-center rounded-lg border border-[#fb7185]/40 text-[#fb7185] hover:bg-[#fb7185]/10 transition-colors"
        >
          <Trash2 size={13} />
        </button>
        {status === 'pending' && (
          <button className="h-8 px-3 flex items-center justify-center rounded-lg border border-white/10 text-[#475569] hover:text-[#94a3b8] hover:border-white/20 transition-colors">
            <BellOff size={13} />
          </button>
        )}
      </div>
    </div>
  );
}

function EmptyInspector() {
  return (
    <div className="h-full flex flex-col items-center justify-center p-6 text-center relative">
      {/* Animated rings */}
      <div className="relative mb-6">
        <div className="w-20 h-20 rounded-full border border-[#22d3ee]/10 animate-glow-pulse" />
        <div className="absolute inset-2 rounded-full border border-[#22d3ee]/20" style={{ animation: 'glow-pulse 3s ease-in-out infinite reverse' }} />
        <div className="absolute inset-5 rounded-full border border-[#22d3ee]/30 flex items-center justify-center">
          <Brain size={22} className="text-[#22d3ee]/40" strokeWidth={1.5} />
        </div>
        {/* Orbital dot */}
        <div className="absolute inset-0 animate-spin" style={{ animationDuration: '8s' }}>
          <div className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1 w-1.5 h-1.5 rounded-full bg-[#22d3ee]" style={{ boxShadow: '0 0 6px #22d3ee' }} />
        </div>
      </div>
      <p className="text-[#94a3b8] text-[13px] mb-1">
        Select a node or event to inspect
      </p>
      <p className="text-[#475569] text-[11px] mb-4">
        Click any memory on the graph
      </p>
      {/* Mini stats row */}
      <div className="flex items-center gap-4 px-4 py-2 rounded-lg border border-white/5" style={{ backgroundColor: 'rgba(15, 23, 42, 0.4)' }}>
        {[
          { label: 'Facts', value: 47 },
          { label: 'Reminders', value: 12 },
          { label: 'Changes', value: 3 },
        ].map((s) => (
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
}: Props) {
  return (
    <Card className="h-full relative flex flex-col" noPadding>
      {/* Collapse handle */}
      <button
        onClick={onToggleCollapse}
        className="
          absolute left-0 top-1/2 -translate-x-1/2 z-10
          w-5 h-10 flex items-center justify-center
          rounded-full bg-[#1e293b] border border-white/10
          text-[#475569] hover:text-[#94a3b8] hover:border-white/20
          transition-all duration-150
        "
      >
        {collapsed ? <ChevronLeft size={12} /> : <ChevronRight size={12} />}
      </button>

      <AnimatePresence mode="wait">
        {collapsed ? (
          <motion.div
            key="collapsed"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="h-full flex flex-col items-center justify-center gap-4 py-4"
          >
            <Brain size={20} className="text-[#475569]" />
          </motion.div>
        ) : (
          <motion.div
            key="expanded"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="h-full overflow-y-auto"
          >
            <AnimatePresence mode="wait">
              {selectedNode ? (
                <motion.div
                  key={`node-${selectedNode.id}`}
                  initial={{ opacity: 0, x: 10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -10 }}
                  transition={{ duration: 0.2 }}
                >
                  <NodeEditor node={selectedNode} onNodeSelect={onNodeSelect} />
                </motion.div>
              ) : selectedReminder ? (
                <motion.div
                  key={`reminder-${selectedReminder.id}`}
                  initial={{ opacity: 0, x: 10 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -10 }}
                  transition={{ duration: 0.2 }}
                >
                  <ReminderEditor
                    reminder={selectedReminder}
                    onReminderSelect={() => {}}
                  />
                </motion.div>
              ) : (
                <motion.div
                  key="empty"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
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
