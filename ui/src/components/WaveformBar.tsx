import { useRef, useEffect } from 'react';
import gsap from 'gsap';
import type { VoiceState } from '@/hooks/useVoiceState';

interface WaveformBarProps {
  state: VoiceState;
}

const BAR_COUNT = 40;

export default function WaveformBar({ state }: WaveformBarProps) {
  const barsRef = useRef<HTMLDivElement[]>([]);
  const tweensRef = useRef<gsap.core.Tween[]>([]);
  const stateRef = useRef<VoiceState>('idle');

  stateRef.current = state;

  useEffect(() => {
    // Kill previous tweens
    tweensRef.current.forEach(t => t.kill());
    tweensRef.current = [];

    const bars = barsRef.current.filter(Boolean);
    if (bars.length === 0) return;

    if (state === 'idle') {
      // Gentle ambient wave
      bars.forEach((bar, i) => {
        const tween = gsap.to(bar, {
          scaleY: 0.15 + Math.sin(i * 0.4) * 0.1,
          duration: 1.5 + Math.random() * 0.5,
          yoyo: true,
          repeat: -1,
          ease: 'sine.inOut',
          delay: i * 0.03,
        });
        tweensRef.current.push(tween);
      });
    } else if (state === 'listening') {
      // Responsive wave pattern
      bars.forEach((bar, i) => {
        const tween = gsap.to(bar, {
          scaleY: 0.3 + Math.abs(Math.sin(i * 0.3)) * 0.4,
          duration: 0.8,
          yoyo: true,
          repeat: -1,
          ease: 'sine.inOut',
          delay: i * 0.02,
        });
        tweensRef.current.push(tween);
      });
    } else if (state === 'thinking') {
      // Chaotic fast jitter
      bars.forEach((bar, i) => {
        const tween = gsap.to(bar, {
          scaleY: () => 0.2 + Math.random() * 0.8,
          duration: 0.1,
          repeat: -1,
          ease: 'none',
          delay: i * 0.01,
        });
        tweensRef.current.push(tween);
      });
    } else if (state === 'synthesizing') {
      // Minimal subtle pulse (preparing to speak)
      bars.forEach((bar, i) => {
        const tween = gsap.to(bar, {
          scaleY: 0.2 + Math.sin(i * 0.4) * 0.08,
          duration: 2.0 + Math.random() * 0.5,
          yoyo: true,
          repeat: -1,
          ease: 'sine.inOut',
          delay: i * 0.03,
        });
        tweensRef.current.push(tween);
      });
    } else if (state === 'speaking') {
      // Dynamic speech pattern
      bars.forEach((bar, i) => {
        const baseScale = 0.3 + Math.sin(i * 0.25) * 0.2;
        const tween = gsap.to(bar, {
          scaleY: baseScale + 0.5,
          duration: 0.4 + Math.random() * 0.3,
          yoyo: true,
          repeat: -1,
          ease: 'sine.inOut',
          delay: i * 0.015,
        });
        tweensRef.current.push(tween);
      });
    }

    return () => {
      tweensRef.current.forEach(t => t.kill());
    };
  }, [state]);

  const barColor = state === 'listening' ? '#00E5A0' : '#22d3ee';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 3,
        height: 50,
        width: 220,
      }}
    >
      {Array.from({ length: BAR_COUNT }).map((_, i) => (
        <div
          key={i}
          ref={el => { if (el) barsRef.current[i] = el; }}
          style={{
            width: 3,
            height: '100%',
            background: barColor,
            borderRadius: 2,
            opacity: 0.6 + Math.sin((i / BAR_COUNT) * Math.PI) * 0.4,
            transformOrigin: 'center',
            transform: 'scaleY(0.15)',
            transition: 'background-color 0.4s ease',
          }}
        />
      ))}
    </div>
  );
}
