import { useState, useMemo, useEffect, useRef } from 'react';
import Card from '@/console/components/Card';
import MemoryGraphZone from './graph/MemoryGraphZone';
import { useMemoryDataCtx } from '@/console/services/MemoryDataContext';

interface Props {
  selectedNodeId: string | null;
  onNodeSelect: (id: string | null) => void;
}

function useCountUp(target: number, duration: number = 1200) {
  const [value, setValue] = useState(0);
  const startTimeRef = useRef<number | null>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    startTimeRef.current = null;
    const animate = (timestamp: number) => {
      if (!startTimeRef.current) startTimeRef.current = timestamp;
      const elapsed = timestamp - startTimeRef.current;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(eased * target));
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate);
      }
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, duration]);

  return value;
}

export default function Zone1MemoryCore({ selectedNodeId, onNodeSelect }: Props) {
  const { graphNodes, reminders: liveReminders, episodic } = useMemoryDataCtx();
  const stats = useMemo(() => {
    const facts = graphNodes.filter((n) => n.type === 'memory').length;
    const reminders = liveReminders.filter((r) => r.status === 'pending').length;
    const weekAgo = Date.now() - 7 * 24 * 3600 * 1000;
    const changes = episodic.filter((e) => {
      const t = e.date ? Date.parse(e.date) : NaN;
      return Number.isFinite(t) && t >= weekAgo;
    }).length;
    return { facts, reminders, changes };
  }, [graphNodes, liveReminders, episodic]);

  const animatedFacts = useCountUp(stats.facts);
  const animatedReminders = useCountUp(stats.reminders);
  const animatedChanges = useCountUp(stats.changes);

  return (
    <Card className="h-full flex flex-col relative overflow-hidden" noPadding>
      {/* Graph fills the entire card — header is rendered inside MemoryGraphZone */}
      <div className="flex-1 min-h-0 relative">
        <MemoryGraphZone
          selectedNodeId={selectedNodeId}
          onNodeSelect={onNodeSelect}
        />
      </div>

      {/* Empty state overlay */}
      {!selectedNodeId && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 pointer-events-none z-30">
          <div className="text-center">
            <p className="text-[#94a3b8] text-xs mb-1.5">
              {stats.facts === 0
                ? 'No facts stored yet — Jarvis learns from every conversation'
                : 'Select a memory node to inspect or edit'}
            </p>
            <p className="text-[#475569] text-[11px]">
              <span className="text-[#22d3ee] font-mono tabular-nums">{animatedFacts}</span>{' '}
              <span className="text-[#475569]">facts</span>
              <span className="mx-1.5 text-[#334155]">•</span>
              <span className="text-[#22d3ee] font-mono tabular-nums">{animatedReminders}</span>{' '}
              <span className="text-[#475569]">reminders</span>
              <span className="mx-1.5 text-[#334155]">•</span>
              <span className="text-[#22d3ee] font-mono tabular-nums">{animatedChanges}</span>{' '}
              <span className="text-[#475569]">changes this week</span>
            </p>
          </div>
        </div>
      )}
    </Card>
  );
}
