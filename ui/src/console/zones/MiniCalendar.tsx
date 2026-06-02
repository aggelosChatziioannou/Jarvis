import { useState, useMemo } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import {
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  eachDayOfInterval,
  isSameMonth,
  isToday,
  isSameDay,
  addMonths,
  subMonths,
  format,
} from 'date-fns';

interface Props {
  eventDates?: Date[];
  memoryDates?: Date[];
  onDayClick?: (date: Date) => void;
  selectedDate?: Date | null;
}

export default function MiniCalendar({ eventDates = [], memoryDates = [], onDayClick, selectedDate }: Props) {
  const [currentMonth, setCurrentMonth] = useState(new Date(2026, 4, 29));
  const today = new Date(2026, 4, 29);

  const days = useMemo(() => {
    const monthStart = startOfMonth(currentMonth);
    const monthEnd = endOfMonth(currentMonth);
    const calStart = startOfWeek(monthStart, { weekStartsOn: 0 });
    const calEnd = endOfWeek(monthEnd, { weekStartsOn: 0 });
    return eachDayOfInterval({ start: calStart, end: calEnd });
  }, [currentMonth]);

  const weekDays = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];

  const hasEvent = (day: Date) => eventDates.some((d) => isSameDay(d, day));
  const hasMemory = (day: Date) => memoryDates.some((d) => isSameDay(d, day));

  return (
    <div className="p-4">
      {/* Month navigation */}
      <div className="flex items-center justify-between mb-3">
        <button
          onClick={() => setCurrentMonth(subMonths(currentMonth, 1))}
          className="p-1 rounded hover:bg-white/5 transition-colors text-[#475569] hover:text-[#94a3b8]"
        >
          <ChevronLeft size={16} />
        </button>
        <span className="text-[13px] font-semibold text-[#f8fafc]">
          {format(currentMonth, 'MMMM yyyy')}
        </span>
        <button
          onClick={() => setCurrentMonth(addMonths(currentMonth, 1))}
          className="p-1 rounded hover:bg-white/5 transition-colors text-[#475569] hover:text-[#94a3b8]"
        >
          <ChevronRight size={16} />
        </button>
      </div>

      {/* Week day headers */}
      <div className="grid grid-cols-7 gap-0 mb-1">
        {weekDays.map((wd) => (
          <div key={wd} className="text-center text-[11px] text-[#475569] font-medium py-1">
            {wd}
          </div>
        ))}
      </div>

      {/* Day grid */}
      <div className="grid grid-cols-7 gap-0.5">
        {days.map((day, i) => {
          const inMonth = isSameMonth(day, currentMonth);
          const isTodayDate = isToday(day) && isSameMonth(day, today);
          const isSelected = selectedDate && isSameDay(day, selectedDate);
          const dayHasEvent = hasEvent(day);
          const dayHasMemory = hasMemory(day);

          return (
            <button
              key={i}
              onClick={() => onDayClick?.(day)}
              className={`
                relative h-9 flex flex-col items-center justify-center rounded-lg
                transition-all duration-150 text-[12px]
                ${!inMonth ? 'text-[#475569]/40' : ''}
                ${inMonth && !isTodayDate ? 'text-[#f8fafc]' : ''}
                ${isTodayDate ? 'bg-[#22d3ee] text-[#0a0e17] font-semibold' : ''}
                ${isSelected && !isTodayDate ? 'ring-1 ring-[#22d3ee]' : ''}
                ${inMonth && !isTodayDate ? 'hover:bg-[#22d3ee]/5 hover:scale-[1.02]' : ''}
              `}
            >
              <span>{format(day, 'd')}</span>
              {/* Event dots */}
              {(dayHasEvent || dayHasMemory) && inMonth && (
                <div className="flex gap-0.5 mt-0.5">
                  {dayHasEvent && (
                    <div className="w-1 h-1 rounded-full bg-[#fbbf24]" />
                  )}
                  {dayHasMemory && (
                    <div className="w-1 h-1 rounded-full bg-[#475569]" />
                  )}
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
