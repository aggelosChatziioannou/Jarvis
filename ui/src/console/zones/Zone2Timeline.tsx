import { useMemo, useState } from 'react';
import { parseISO } from 'date-fns';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronLeft, ChevronRight, Calendar, Clock } from 'lucide-react';
import Card from '@/console/components/Card';
import MiniCalendar from './MiniCalendar';
import EventStream from './EventStream';
import { sampleReminders, sampleEpisodic } from '@/console/data/demo';
import type { Reminder } from '@/console/types';

interface Props {
  onReminderSelect: (reminder: Reminder | null) => void;
  selectedReminder: Reminder | null;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export default function Zone2Timeline({
  onReminderSelect,
  selectedReminder,
  collapsed = false,
  onToggleCollapse,
}: Props) {
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);

  const eventDates = useMemo(
    () => sampleReminders.map((r) => parseISO(r.date)),
    []
  );

  const memoryDates = useMemo(
    () => sampleEpisodic.map((e) => parseISO(e.date)),
    []
  );

  return (
    <Card className="h-full flex flex-col relative" noPadding>
      {/* Collapse handle — floating on left edge */}
      {onToggleCollapse && (
        <button
          onClick={onToggleCollapse}
          className="absolute left-0 top-1/2 -translate-x-1/2 z-10 w-5 h-10 flex items-center justify-center rounded-full bg-[#1e293b] border border-white/10 text-[#475569] hover:text-[#94a3b8] hover:border-white/20 transition-all duration-150"
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronLeft size={12} />}
        </button>
      )}

      <AnimatePresence mode="wait">
        {collapsed ? (
          <motion.div
            key="collapsed"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="h-full flex flex-col items-center justify-center gap-4 py-4"
          >
            <Calendar size={18} className="text-[#475569]" />
            <Clock size={18} className="text-[#475569]" />
          </motion.div>
        ) : (
          <motion.div
            key="expanded"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="h-full flex flex-col"
          >
            {/* Header */}
            <div className="px-5 pt-4 pb-2 border-b border-white/5">
              <h2 className="text-[11px] font-semibold tracking-[0.08em] text-[#94a3b8] uppercase">
                Timeline
              </h2>
            </div>

            {/* Calendar */}
            <div className="shrink-0 border-b border-white/5">
              <MiniCalendar
                eventDates={eventDates}
                memoryDates={memoryDates}
                onDayClick={setSelectedDate}
                selectedDate={selectedDate}
              />
            </div>

            {/* Event stream header */}
            <div className="px-4 pt-3 pb-1 flex items-center justify-between">
              <h3 className="text-[11px] font-semibold tracking-[0.08em] text-[#94a3b8] uppercase">
                Events
              </h3>
              <span className="text-[10px] text-[#475569]">{sampleReminders.length + sampleEpisodic.length} items</span>
            </div>

            {/* Event stream */}
            <div className="flex-1 min-h-0">
              <EventStream
                onReminderSelect={onReminderSelect}
                selectedReminder={selectedReminder}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
