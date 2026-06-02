import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Pencil, Bell, Check, X } from 'lucide-react';
import { useMemoryDataCtx } from '@/console/services/MemoryDataContext';
import type { Reminder, EpisodicMemory } from '@/console/types';

interface Props {
  onReminderSelect: (reminder: Reminder | null) => void;
  selectedReminder: Reminder | null;
}

const statusBorderColor: Record<string, string> = {
  pending: '#22d3ee',
  completed: '#475569',
  snoozed: '#fbbf24',
  cancelled: '#475569',
};

function ReminderCard({
  reminder,
  isSelected,
  onClick,
  onSnooze,
  onComplete,
}: {
  reminder: Reminder;
  isSelected: boolean;
  onClick: () => void;
  onSnooze: () => void;
  onComplete: () => void;
}) {
  const borderColor = statusBorderColor[reminder.status] || '#475569';

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: -40 }}
      transition={{ duration: 0.2 }}
      onClick={onClick}
      className={`relative rounded-lg p-3 cursor-pointer transition-all duration-150 ${
        isSelected ? 'bg-white/[0.05]' : 'bg-[#0a0e17] hover:bg-white/[0.03]'
      }`}
      style={{ borderLeft: `3px solid ${borderColor}` }}
    >
      <div className="text-[11px] text-[#22d3ee] font-mono mb-0.5">{reminder.time || '--:--'}</div>
      <div className="text-[13px] text-[#f8fafc] mb-1.5 leading-tight">{reminder.title}</div>
      <div className="flex gap-1">
        <button
          onClick={(e) => { e.stopPropagation(); onClick(); }}
          title="Edit"
          className="p-1 rounded hover:bg-white/5 transition-colors text-[#475569] hover:text-[#94a3b8]"
        >
          <Pencil size={12} />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onSnooze(); }}
          title="Snooze 10 min"
          className="p-1 rounded hover:bg-white/5 transition-colors text-[#475569] hover:text-[#fbbf24]"
        >
          <Bell size={12} />
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); onComplete(); }}
          title="Mark done"
          className="p-1 rounded hover:bg-white/5 transition-colors text-[#475569] hover:text-[#34d399]"
        >
          <Check size={12} />
        </button>
      </div>
      {reminder.status === 'snoozed' && (
        <span className="absolute top-2 right-2 text-[10px] text-[#fbbf24]">Snoozed</span>
      )}
      {reminder.status === 'completed' && (
        <span className="absolute top-2 right-2 text-[10px] text-[#475569] line-through">Done</span>
      )}
    </motion.div>
  );
}

function EpisodicCard({ memory }: { memory: EpisodicMemory }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 0.6 }}
      exit={{ opacity: 0, x: -40 }}
      transition={{ duration: 0.2 }}
      className="rounded-lg p-3 border border-dashed border-white/5 bg-[#0a0e17]/50"
    >
      <div className="text-[11px] text-[#475569] font-mono mb-1">{memory.date}</div>
      <div className="text-[12px] text-[#94a3b8] italic leading-relaxed">
        &ldquo;{memory.content}&rdquo;
      </div>
      <div className="text-[10px] text-[#475569]/60 mt-1.5">—— from memory ——</div>
    </motion.div>
  );
}

function todayISO(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export default function EventStream({ onReminderSelect, selectedReminder }: Props) {
  const { reminders, episodic, createReminder, completeReminder, snoozeReminder } = useMemoryDataCtx();
  const [showAddForm, setShowAddForm] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newTime, setNewTime] = useState('12:00');
  const [busy, setBusy] = useState(false);

  const handleAdd = async () => {
    if (!newTitle.trim() || busy) return;
    setBusy(true);
    try {
      await createReminder(newTitle.trim(), todayISO(), newTime);
      setNewTitle('');
      setNewTime('12:00');
      setShowAddForm(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto space-y-2 px-4 pb-2 min-h-0">
        <AnimatePresence mode="popLayout">
          {reminders.map((reminder) => (
            <ReminderCard
              key={reminder.id}
              reminder={reminder}
              isSelected={selectedReminder?.id === reminder.id}
              onClick={() => onReminderSelect(selectedReminder?.id === reminder.id ? null : reminder)}
              onSnooze={() => void snoozeReminder(reminder.id)}
              onComplete={() => void completeReminder(reminder.id)}
            />
          ))}
          {episodic.map((memory) => (
            <EpisodicCard key={memory.id} memory={memory} />
          ))}
        </AnimatePresence>
      </div>

      <div className="p-3 border-t border-white/5">
        <AnimatePresence mode="wait">
          {showAddForm ? (
            <motion.div
              key="form"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="space-y-2"
            >
              <input
                type="text"
                placeholder="Reminder title..."
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                autoFocus
                className="w-full h-8 px-3 rounded-md bg-[#1e293b] text-[#f8fafc] text-[12px] placeholder:text-[#475569] border border-transparent focus:border-[#22d3ee] focus:outline-none"
              />
              <div className="flex gap-2">
                <input
                  type="time"
                  value={newTime}
                  onChange={(e) => setNewTime(e.target.value)}
                  className="flex-1 h-8 px-2 rounded-md bg-[#1e293b] text-[#f8fafc] text-[12px] border border-transparent focus:border-[#22d3ee] focus:outline-none"
                />
                <button
                  onClick={() => void handleAdd()}
                  disabled={busy}
                  className="h-8 px-3 rounded-md bg-[#22d3ee] text-[#0a0e17] text-[12px] font-medium hover:bg-[#22d3ee]/80 transition-colors disabled:opacity-50"
                >
                  Save
                </button>
                <button
                  onClick={() => setShowAddForm(false)}
                  className="h-8 px-2 rounded-md border border-white/10 text-[#475569] hover:text-[#94a3b8] transition-colors"
                >
                  <X size={14} />
                </button>
              </div>
            </motion.div>
          ) : (
            <motion.button
              key="button"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowAddForm(true)}
              className="w-8 h-8 rounded-full flex items-center justify-center bg-transparent border border-[#22d3ee]/40 text-[#22d3ee] hover:bg-[#22d3ee] hover:text-[#0a0e17] hover:shadow-[0_0_12px_rgba(34,211,238,0.3)] transition-all duration-200"
            >
              <Plus size={16} />
            </motion.button>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
