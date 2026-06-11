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
// A failed subsystem check is re-probed at this cadence. Without retries the
// walker stalled forever when the HUD opened before the daemon finished
// initialising (each check used to run exactly once and cache `false`).
const CHECK_RETRY_MS = 800;

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
 * minimum display duration and its real API check to pass; failed checks
 * are retried so a HUD opened mid-daemon-boot still completes.
 *
 * Liveness is tracked PER EFFECT RUN (a closed-over `alive` flag), never via
 * a ref shared between effects: the fast-forward state updates re-ran the
 * walker effect, whose cleanup flipped the shared ref false BEFORE the
 * fast-forward completion timer fired — `isComplete` never set, and the HUD
 * sat on "JARVIS / 100% / Ready" forever. The race only shows when the
 * daemon answers all probes in under the threshold (i.e. when it is FAST).
 */
export function useBootSequence(enabled: boolean): BootSequenceState {
  const [activeIndex, setActiveIndex] = useState(0);
  const [progress, setProgress] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [fastForwarded, setFastForwarded] = useState(false);

  const stageStartRef = useRef<number>(0);
  const checksDoneRef = useRef<Record<string, boolean>>({});
  const retryAtRef = useRef<Record<string, number>>({});

  const runCheck = useCallback(async (def: StageDef) => {
    try {
      const ok = await def.check();
      checksDoneRef.current[def.id] = ok;
      return ok;
    } catch {
      checksDoneRef.current[def.id] = false;
      return false;
    }
  }, []);

  // Initial parallel probe → fast-forward decision
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let timer = 0;

    const probeStart = performance.now();
    const nonFinal = STAGE_DEFS.slice(0, -1);

    Promise.all(nonFinal.map((d) => runCheck(d))).then((results) => {
      if (!alive) return;
      const elapsed = performance.now() - probeStart;
      const allOk = results.every(Boolean);
      if (allOk && elapsed < FAST_FORWARD_THRESHOLD_MS) {
        setFastForwarded(true);
        setActiveIndex(STAGE_DEFS.length - 1);
        setProgress(100);
        timer = window.setTimeout(() => {
          if (alive) setIsComplete(true);
        }, STAGE_DEFS[STAGE_DEFS.length - 1].minDuration);
      }
    });

    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [enabled, runCheck]);

  // Sequential stage walker (skipped when fast-forwarded)
  useEffect(() => {
    if (!enabled || fastForwarded || isComplete) return;
    let alive = true;
    let raf = 0;
    stageStartRef.current = performance.now();

    const tick = () => {
      if (!alive) return;
      const now = performance.now();
      const currentDef = STAGE_DEFS[activeIndex];
      const elapsed = now - stageStartRef.current;
      const checkOk = checksDoneRef.current[currentDef.id] ?? false;
      const timeOk = elapsed >= currentDef.minDuration;

      // Re-probe a failed check: early HUD opens race the daemon's own
      // boot; a one-shot `false` must not stall the sequence forever.
      if (
        checksDoneRef.current[currentDef.id] === false &&
        now - (retryAtRef.current[currentDef.id] ?? 0) > CHECK_RETRY_MS
      ) {
        retryAtRef.current[currentDef.id] = now;
        runCheck(currentDef);
      }

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
      raf = requestAnimationFrame(tick);
    };

    if (checksDoneRef.current[STAGE_DEFS[0].id] === undefined) {
      runCheck(STAGE_DEFS[0]);
    }
    raf = requestAnimationFrame(tick);

    return () => {
      alive = false;
      if (raf) cancelAnimationFrame(raf);
    };
  }, [enabled, fastForwarded, isComplete, activeIndex, runCheck]);

  return {
    stages: STAGE_DEFS.map((d) => ({ id: d.id, text: d.text })),
    activeStageIndex: activeIndex,
    progress,
    isComplete,
  };
}
