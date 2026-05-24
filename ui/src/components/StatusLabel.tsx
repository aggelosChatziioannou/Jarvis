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
  speaking: 'SPEAKING',
};

const STATE_COLOR: Record<VoiceState, string> = {
  idle: '#5A7182',
  listening: '#00E5A0',
  thinking: '#FFB800',
  speaking: '#FFB800',
};

export default function StatusLabel({ state }: StatusLabelProps) {
  const textRef = useRef<HTMLDivElement>(null);
  const ellipsisRef = useRef<number>(0);
  const [displayText, setDisplayText] = useState(STATE_TEXT.idle);
  const intervalRef = useRef<number | null>(null);

  // Handle state changes with fade animation
  useEffect(() => {
    const el = textRef.current;
    if (!el) return;

    // Clear previous ellipsis interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    const newText = STATE_TEXT[state];

    // Fade out → change text → fade in
    gsap.to(el, {
      opacity: 0,
      duration: 0.15,
      ease: 'power2.in',
      onComplete: () => {
        if (state === 'thinking') {
          // Start ellipsis animation
          ellipsisRef.current = 0;
          setDisplayText('PROCESSING.');

          intervalRef.current = window.setInterval(() => {
            ellipsisRef.current = (ellipsisRef.current + 1) % 3;
            const dots = '.'.repeat(ellipsisRef.current + 1);
            setDisplayText(`PROCESSING${dots}`);
          }, 500);
        } else {
          setDisplayText(newText);
        }

        gsap.to(el, {
          opacity: 1,
          duration: 0.25,
          ease: 'power2.out',
        });
      },
    });

    // Color tween
    gsap.to(el, {
      color: STATE_COLOR[state],
      duration: 0.4,
      ease: 'power2.inOut',
    });

    // Speaking glow
    if (state === 'speaking') {
      gsap.to(el, {
        textShadow: '0 0 12px rgba(255, 184, 0, 0.4)',
        duration: 0.4,
      });
    } else {
      gsap.to(el, {
        textShadow: '0 0 0px rgba(255, 184, 0, 0)',
        duration: 0.4,
      });
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [state]);

  return (
    <div
      ref={textRef}
      style={{
        fontFamily: "'Inter', sans-serif",
        fontSize: 13,
        fontWeight: 400,
        letterSpacing: '0.08em',
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
