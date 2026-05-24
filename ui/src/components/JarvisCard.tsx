import { useRef, useEffect, useState, useCallback } from 'react';
import gsap from 'gsap';
import type { VoiceState } from '@/hooks/useVoiceState';
import WaveformRings from './WaveformRings';
import StatusLabel from './StatusLabel';
import ControlButton from './ControlButton';

interface JarvisCardProps {
  state: VoiceState;
  isMuted: boolean;
  onMuteToggle: () => void;
  onStop: () => void;
  onStartDemo: () => void;
}

// SVG Icons
function MicrophoneIcon({ muted }: { muted: boolean }) {
  if (muted) {
    return (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#2A3F50" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />
        <line x1="1" y1="1" x2="23" y2="23" />
      </svg>
    );
  }
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#E8F4F8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="#E8F4F8">
      <rect x="4" y="4" width="16" height="16" rx="3" />
    </svg>
  );
}

function MinimizeIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

export default function JarvisCard({ state, isMuted, onMuteToggle, onStop, onStartDemo }: JarvisCardProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const dotsRef = useRef<HTMLDivElement[]>([]);
  const borderTweenRef = useRef<gsap.core.Tween | null>(null);
  const [stopFlash, setStopFlash] = useState(false);
  const prevStateRef = useRef<VoiceState>('idle');

  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // We check window.hudMove on every drag — not at mount — because the
  // PyQt JS bridge injects it after the page loads, which can be AFTER
  // React first renders. Caching it once would leave the drag broken
  // when the page finishes loading.
  const hasHudBridge = (): boolean =>
    typeof window !== 'undefined' && typeof (window as any).hudMove === 'function';

  // Border breathing animation
  useEffect(() => {
    const card = cardRef.current;
    if (!card) return;

    // Kill previous border animation
    if (borderTweenRef.current) {
      borderTweenRef.current.kill();
      borderTweenRef.current = null;
    }

    if (state === 'speaking' || state === 'thinking') {
      borderTweenRef.current = gsap.to(card, {
        boxShadow: '0 0 60px rgba(0, 212, 255, 0.12), 0 8px 32px rgba(0, 0, 0, 0.5)',
        duration: 1.5,
        yoyo: true,
        repeat: -1,
        ease: 'sine.inOut',
      });
    } else {
      gsap.to(card, {
        boxShadow: '0 0 40px rgba(0, 212, 255, 0.06), 0 8px 32px rgba(0, 0, 0, 0.5)',
        duration: 0.6,
        ease: 'power2.out',
      });
    }
  }, [state]);

  // Brand dots animation
  useEffect(() => {
    const isActive = state !== 'idle';
    dotsRef.current.forEach((dot, i) => {
      if (!dot) return;
      gsap.to(dot, {
        backgroundColor: isActive ? '#00D4FF' : '#5A7182',
        duration: 0.3,
        delay: isActive ? i * 0.15 : 0,
        ease: 'power2.out',
      });
    });
  }, [state]);

  // Stop flash effect
  useEffect(() => {
    const prev = prevStateRef.current;
    if (prev !== 'idle' && state === 'idle') {
      setStopFlash(true);
      setTimeout(() => setStopFlash(false), 400);
    }
    prevStateRef.current = state;
  }, [state]);

  // Global mouse move/up for dragging
  useEffect(() => {
    if (!isDragging) return;

    const handleMove = (e: MouseEvent) => {
      const dx = e.clientX - dragStartRef.current.x;
      const dy = e.clientY - dragStartRef.current.y;
      dragStartRef.current = { x: e.clientX, y: e.clientY };
      const fn = (window as any).hudMove;
      if (typeof fn === 'function') fn(dx, dy);
    };

    const handleUp = () => {
      setIsDragging(false);
    };

    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [isDragging]);

  const handleCardClick = useCallback((e: React.MouseEvent) => {
    // Ignore clicks on buttons or the window-control bar
    if ((e.target as HTMLElement).closest('button')) return;
    onStartDemo();
  }, [onStartDemo]);

  const handleDragMouseDown = useCallback((e: React.MouseEvent) => {
    if (!hasHudBridge()) return;
    e.preventDefault();
    setIsDragging(true);
    dragStartRef.current = { x: e.clientX, y: e.clientY };
  }, []);

  const handleMinimize = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (typeof window !== 'undefined' && (window as any).hudMinimize) {
      (window as any).hudMinimize();
    }
  }, []);

  const handleClose = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (typeof window !== 'undefined' && (window as any).hudClose) {
      (window as any).hudClose();
    }
  }, []);

  return (
    <div
      ref={cardRef}
      onClick={handleCardClick}
      style={{
        width: 320,
        height: 420,
        background: 'rgba(8, 16, 30, 0.92)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        border: `1px solid ${stopFlash ? 'rgba(255, 59, 92, 0.6)' : 'rgba(0, 212, 255, 0.12)'}`,
        borderRadius: 20,
        boxShadow: '0 0 40px rgba(0, 212, 255, 0.06), 0 8px 32px rgba(0, 0, 0, 0.5)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: 28,
        position: 'relative',
        overflow: 'hidden',
        cursor: state === 'idle' ? 'pointer' : 'default',
        transition: 'border-color 0.3s ease',
        userSelect: 'none',
      }}
    >
      {/* Top - Brand Label + Window Controls */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          width: '100%',
          marginBottom: 32,
        }}
      >
        <div
          style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1 }}
          onMouseDown={handleDragMouseDown}
          title="Drag to move"
        >
          <span
            className="font-orbitron"
            style={{
              fontSize: 11,
              fontWeight: 500,
              color: 'rgba(0, 212, 255, 0.4)',
              letterSpacing: '0.15em',
              textTransform: 'uppercase',
              cursor: 'move',
            }}
          >
            JARVIS
          </span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {[0, 1, 2].map(i => (
              <div
                key={i}
                ref={el => { if (el) dotsRef.current[i] = el; }}
                style={{
                  width: 4,
                  height: 4,
                  borderRadius: '50%',
                  background: '#5A7182',
                  transition: 'background-color 0.3s ease',
                }}
              />
            ))}
          </div>
        </div>

        {/* Window controls — always rendered; handlers no-op gracefully if no PyQt bridge */}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginLeft: 8 }}>
            <button
              onClick={handleMinimize}
              onMouseDown={(e) => e.stopPropagation()}
              title="Minimize"
              style={{
                width: 22,
                height: 22,
                borderRadius: 6,
                border: '1px solid rgba(255,255,255,0.08)',
                background: 'transparent',
                color: '#5A7182',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                transition: 'all 0.2s',
                padding: 0,
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.06)';
                (e.currentTarget as HTMLButtonElement).style.color = '#E8F4F8';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                (e.currentTarget as HTMLButtonElement).style.color = '#5A7182';
              }}
            >
              <MinimizeIcon />
            </button>
            <button
              onClick={handleClose}
              onMouseDown={(e) => e.stopPropagation()}
              title="Close"
              style={{
                width: 22,
                height: 22,
                borderRadius: 6,
                border: '1px solid rgba(255,255,255,0.08)',
                background: 'transparent',
                color: '#5A7182',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                transition: 'all 0.2s',
                padding: 0,
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255, 59, 92, 0.15)';
                (e.currentTarget as HTMLButtonElement).style.color = '#f87171';
                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255, 59, 92, 0.3)';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                (e.currentTarget as HTMLButtonElement).style.color = '#5A7182';
                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.08)';
              }}
            >
              <CloseIcon />
            </button>
          </div>
      </div>

      {/* Middle - Waveform */}
      <WaveformRings state={state} />

      {/* Status Label */}
      <StatusLabel state={state} />

      {/* Spacer */}
      <div style={{ flex: 1, minHeight: 24 }} />

      {/* Bottom - Control Bar */}
      <div style={{ display: 'flex', gap: 16, marginTop: 'auto' }}>
        <ControlButton
          icon={<MicrophoneIcon muted={isMuted} />}
          onClick={onMuteToggle}
          active={!isMuted}
          tooltip={isMuted ? 'Unmute (M)' : 'Mute (M)'}
        />
        <ControlButton
          icon={<StopIcon />}
          onClick={onStop}
          variant="danger"
          tooltip="Stop (Esc)"
        />
      </div>
    </div>
  );
}
