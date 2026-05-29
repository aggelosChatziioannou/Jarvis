import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '@/lib/api';

export interface BootStage {
  id: string;
  text: string;
}

interface StageDef extends BootStage {
  check: () => Promise<boolean>;
  minDuration: number;
}

const STAGE_DEFS: StageDef[] = [
  {
    id: 'core',
    text: 'Loading configuration...',
    check: () => api.health().then(() => true).catch(() => false),
    minDuration: 400,
  },
  {
    id: 'neural',
    text: 'Loading neural models...',
    check: () => api.llmModels().then(() => true).catch(() => false),
    minDuration: 700,
  },
  {
    id: 'audio',
    text: 'Initializing audio interface...',
    check: () => api.audioDevices().then(() => true).catch(() => false),
    minDuration: 500,
  },
  {
    id: 'mcp',
    text: 'Connecting services...',
    check: () => api.mcps().then(() => true).catch(() => false),
    minDuration: 500,
  },
  {
    id: 'tts',
    text: 'Starting voice engine...',
    check: () => api.ttsCacheStats().then(() => true).catch(() => false),
    minDuration: 400,
  },
  {
    id: 'online',
    text: 'Ready',
    check: () => Promise.resolve(true),
    minDuration: 600,
  },
];

const FAST_FORWARD_THRESHOLD_MS = 350;

interface BootSequenceState {
  stages: BootStage[];
  activeStageIndex: number;
  progress: number;
  isComplete: boolean;
}

/**
 * Drives a minimal boot sequence wired to real daemon readiness.
 *
 * Parallel-probes all subsystems on mount. If every endpoint responds
 * within FAST_FORWARD_THRESHOLD_MS we skip instantly to the final stage.
 * Otherwise we walk through stages sequentially, each waiting for both its
 * minimum display duration and its real API check to pass.
 */
export function useBootSequence(enabled: boolean): BootSequenceState {
  const [activeIndex, setActiveIndex] = useState(0);
  const [progress, setProgress] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [fastForwarded, setFastForwarded] = useState(false);

  const stageStartRef = useRef<number>(0);
  const checksDoneRef = useRef<Record<string, boolean>>({});
  const rafRef = useRef<number>(0);
  const aliveRef = useRef(true);

  const runCheck = useCallback(async (def: StageDef) => {
    try {
      const ok = await def.check();
      if (aliveRef.current) checksDoneRef.current[def.id] = ok;
      return ok;
    } catch {
      checksDoneRef.current[def.id] = false;
      return false;
    }
  }, []);

  // Initial parallel probe → fast-forward decision
  useEffect(() => {
    if (!enabled) return;
    aliveRef.current = true;

    const probeStart = performance.now();
    const nonFinal = STAGE_DEFS.slice(0, -1);

    Promise.all(nonFinal.map((d) => runCheck(d))).then((results) => {
      if (!aliveRef.current) return;
      const elapsed = performance.now() - probeStart;
      const allOk = results.every(Boolean);
      if (allOk && elapsed < FAST_FORWARD_THRESHOLD_MS) {
        setFastForwarded(true);
        setActiveIndex(STAGE_DEFS.length - 1);
        setProgress(100);
        window.setTimeout(() => {
          if (aliveRef.current) setIsComplete(true);
        }, STAGE_DEFS[STAGE_DEFS.length - 1].minDuration);
      }
    });

    return () => {
      aliveRef.current = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [enabled, runCheck]);

  // Sequential stage walker (skipped when fast-forwarded)
  useEffect(() => {
    if (!enabled || fastForwarded || isComplete) return;
    aliveRef.current = true;
    stageStartRef.current = performance.now();

    const tick = () => {
      if (!aliveRef.current) return;
      const now = performance.now();
      const currentDef = STAGE_DEFS[activeIndex];
      const elapsed = now - stageStartRef.current;
      const checkOk = checksDoneRef.current[currentDef.id] ?? false;
      const timeOk = elapsed >= currentDef.minDuration;

      const completed = activeIndex;
      const stageFraction = Math.min(1, elapsed / currentDef.minDuration);
      const totalFraction = (completed + stageFraction) / STAGE_DEFS.length;
      setProgress(Math.round(totalFraction * 100));

      if (timeOk && checkOk) {
        if (activeIndex < STAGE_DEFS.length - 1) {
          setActiveIndex((prev) => prev + 1);
          stageStartRef.current = now;
          const nextDef = STAGE_DEFS[activeIndex + 1];
          if (checksDoneRef.current[nextDef.id] === undefined) {
            runCheck(nextDef);
          }
        } else {
          setProgress(100);
          setIsComplete(true);
          return;
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    if (checksDoneRef.current[STAGE_DEFS[0].id] === undefined) {
      runCheck(STAGE_DEFS[0]);
    }
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      aliveRef.current = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [enabled, fastForwarded, isComplete, activeIndex, runCheck]);

  return {
    stages: STAGE_DEFS.map((d) => ({ id: d.id, text: d.text })),
    activeStageIndex: activeIndex,
    progress,
    isComplete,
  };
}
