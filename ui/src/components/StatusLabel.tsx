import { useRef, useEffect, useState } from 'react';
import gsap from 'gsap';
import type { VoiceState } from '@/hooks/useVoiceState';

interface StatusLabelProps {
  state: VoiceState;
}

const STATE_TEXT: Record<VoiceState, string> = {
  idle: 'AWAITING COMMAND',
  listening: 'LISTENING',
  thinking: 'PROCESSING',
  synthesizing: 'SYNTHESIZING',
  speaking: 'SPEAKING',
};

const STATE_COLOR: Record<VoiceState, string> = {
  idle: '#5A7182',
  listening: '#00E5A0',
  thinking: '#22d3ee',
  synthesizing: '#a78bfa',
  speaking: '#22d3ee',
};

export default function StatusLabel({ state }: StatusLabelProps) {
  const textRef = useRef<HTMLDivElement>(null);
  const ellipsisRef = useRef<number>(0);
  const intervalRef = useRef<number | null>(null);
  const [displayText, setDisplayText] = useState(STATE_TEXT.idle);

  useEffect(() => {
    // Clear any prior ellipsis animation.
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    // CRITICAL: set the label text SYNCHRONOUSLY here — NOT inside a GSAP
    // onComplete. This component renders inside the frameless, always-on-top
    // floating HUD window, which is usually NOT the focused window. QWebEngine
    // (Chromium) throttles/pauses requestAnimationFrame for unfocused windows,
    // and GSAP drives its tweens via rAF — so a text update deferred to a GSAP
    // onComplete would never fire and the label froze (observed: stuck on
    // PROCESSING while Jarvis was actually SPEAKING, and never returning to
    // AWAITING COMMAND). React re-renders are driven by the /ws/state message
    // (not rAF), so writing the text here updates reliably regardless of focus.
    const animated = state === 'thinking' || state === 'synthesizing';
    if (animated) {
      const baseText = state === 'synthesizing' ? 'SYNTHESIZING' : 'PROCESSING';
      ellipsisRef.current = 0;
      setDisplayText(`${baseText}.`);
      // Cosmetic dot animation. setInterval is throttled (not paused) when the
      // window is hidden, so the dots may slow down — but the base word above
      // is already correct, which is what matters.
      intervalRef.current = window.setInterval(() => {
        ellipsisRef.current = (ellipsisRef.current + 1) % 3;
        setDisplayText(`${baseText}${'.'.repeat(ellipsisRef.current + 1)}`);
      }, 500);
    } else {
      setDisplayText(STATE_TEXT[state]);
    }

    // GSAP is now COSMETIC ONLY (fade-in + colour + glow). It must never gate
    // the text update above, or the label freezes when rAF is throttled.
    const el = textRef.current;
    if (el) {
      gsap.fromTo(
        el,
        { opacity: 0.35 },
        { opacity: 1, duration: 0.25, ease: 'power2.out' },
      );
      gsap.to(el, {
        color: STATE_COLOR[state],
        duration: 0.4,
        ease: 'power2.inOut',
      });
      gsap.to(el, {
        textShadow:
          state === 'speaking' || state === 'synthesizing'
            ? '0 0 12px rgba(34, 211, 238, 0.4)'
            : '0 0 0px rgba(34, 211, 238, 0)',
        duration: 0.4,
      });
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [state]);

  return (
    <div
      ref={textRef}
      style={{
        fontFamily: "'Inter', sans-serif",
        fontSize: 13,
        fontWeight: 600,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        marginTop: 28,
        color: STATE_COLOR.idle,
        textAlign: 'center',
        minHeight: 20,
      }}
    >
      {displayText}
    </div>
  );
}
