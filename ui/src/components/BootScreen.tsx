import { useRef, useEffect, useState } from 'react';
import type { BootStage } from '@/hooks/useBootSequence';

interface BootScreenProps {
  stages: BootStage[];
  activeStageIndex: number;
  progress: number;
  isComplete: boolean;
  onTransitionComplete?: () => void;
}

/**
 * Premium minimal boot screen.
 *
 * Clean, professional aesthetic inspired by high-end desktop software
 * (DaVinci Resolve, Adobe CC, JetBrains). No sci-fi effects, no particles,
 * no WebGL. Pure CSS + React state.
 */
export default function BootScreen({
  stages,
  activeStageIndex,
  progress,
  isComplete,
  onTransitionComplete,
}: BootScreenProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(true);
  const [displayPct, setDisplayPct] = useState(0);
  const pctTweenRef = useRef({ v: 0 });
  const rafRef = useRef<number>(0);

  // Smooth percentage counter (interpolated via RAF, not React state churn)
  useEffect(() => {
    const start = pctTweenRef.current.v;
    const end = progress;
    const duration = 400;
    const t0 = performance.now();

    const tick = (now: number) => {
      const elapsed = now - t0;
      const t = Math.min(1, elapsed / duration);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3);
      pctTweenRef.current.v = start + (end - start) * eased;
      setDisplayPct(Math.round(pctTweenRef.current.v));
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [progress]);

  // Fade-out transition on complete
  useEffect(() => {
    if (!isComplete) return;
    const el = containerRef.current;
    if (!el) return;
    el.style.transition = 'opacity 0.4s ease';
    el.style.opacity = '0';
    const timer = window.setTimeout(() => {
      setVisible(false);
      onTransitionComplete?.();
    }, 450);
    return () => clearTimeout(timer);
  }, [isComplete, onTransitionComplete]);

  if (!visible) return null;

  const currentStage = stages[activeStageIndex];

  return (
    <div
      ref={containerRef}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(ellipse at center, #0d1117 0%, #080c14 70%)',
        fontFamily: "'Inter', 'Segoe UI', sans-serif",
      }}
    >
      {/* Wordmark */}
      <h1
        style={{
          fontFamily: "'Inter', sans-serif",
          fontSize: 48,
          fontWeight: 700,
          color: '#ffffff',
          letterSpacing: '0.05em',
          textTransform: 'uppercase',
          margin: 0,
          padding: 0,
          lineHeight: 1.1,
          userSelect: 'none',
          animation: 'bootFadeInUp 0.8s cubic-bezier(0.22, 1, 0.36, 1) forwards',
          opacity: 0,
        }}
      >
        JARVIS
      </h1>

      {/* Progress bar */}
      <div
        style={{
          width: 360,
          height: 2,
          marginTop: 20,
          background: '#1a2332',
          borderRadius: 1,
          overflow: 'hidden',
          animation: 'bootFadeInUp 0.8s 0.15s cubic-bezier(0.22, 1, 0.36, 1) forwards',
          opacity: 0,
        }}
      >
        <div
          style={{
            height: '100%',
            width: '100%',
            background: '#4fd1c5',
            borderRadius: 1,
            transform: `scaleX(${progress / 100})`,
            transformOrigin: 'left',
            transition: 'transform 0.35s cubic-bezier(0.22, 1, 0.36, 1)',
          }}
        />
      </div>

      {/* Percentage */}
      <div
        style={{
          marginTop: 10,
          fontFamily: "'JetBrains Mono', 'Consolas', monospace",
          fontSize: 12,
          fontWeight: 500,
          color: '#475569',
          letterSpacing: '0.08em',
          userSelect: 'none',
          animation: 'bootFadeInUp 0.8s 0.25s cubic-bezier(0.22, 1, 0.36, 1) forwards',
          opacity: 0,
          minHeight: 18,
        }}
      >
        {String(displayPct).padStart(2, '0')}%
      </div>

      {/* Status text */}
      <div
        style={{
          marginTop: 14,
          height: 20,
          fontSize: 13,
          fontWeight: 400,
          color: '#64748b',
          letterSpacing: '0.02em',
          userSelect: 'none',
          animation: 'bootFadeInUp 0.8s 0.35s cubic-bezier(0.22, 1, 0.36, 1) forwards',
          opacity: 0,
        }}
      >
        <StatusText key={currentStage?.id ?? 'empty'} text={currentStage?.text ?? ''} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  StatusText — simple crossfade on change                           */
/* ------------------------------------------------------------------ */

function StatusText({ text }: { text: string }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    setVisible(false);
    const t = window.setTimeout(() => setVisible(true), 50);
    return () => clearTimeout(t);
  }, [text]);

  return (
    <span
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(4px)',
        transition: 'opacity 0.3s ease, transform 0.3s ease',
        display: 'inline-block',
      }}
    >
      {text}
    </span>
  );
}
