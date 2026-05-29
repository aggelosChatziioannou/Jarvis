import { useRef, useEffect, useState } from 'react';
import gsap from 'gsap';
import type { VoiceState } from '@/hooks/useVoiceState';
import OrbCore from './OrbCore';
import WaveformBar from './WaveformBar';
import StatusLabel from './StatusLabel';
import ControlButton from './ControlButton';

interface JarvisPanelProps {
  state: VoiceState;
  isMuted: boolean;
  onMuteToggle: () => void;
  onStop: () => void;
  onStartDemo: () => void;
}

function MicrophoneIcon({ muted }: { muted: boolean }) {
  if (muted) {
    return (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2A3F50" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />
        <line x1="1" y1="1" x2="23" y2="23" />
      </svg>
    );
  }
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#E8F4F8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="#E8F4F8">
      <rect x="4" y="4" width="16" height="16" rx="3" />
    </svg>
  );
}

export default function JarvisPanel({ state, isMuted, onMuteToggle, onStop, onStartDemo }: JarvisPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [stopFlash, setStopFlash] = useState(false);
  const prevStateRef = useRef<VoiceState>('idle');

  // Panel border breathing
  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;

    if (state === 'speaking') {
      gsap.to(panel, {
        boxShadow: '0 0 50px rgba(34,211,238,0.15), 0 8px 40px rgba(0,0,0,0.6), inset 0 1px 0 rgba(34,211,238,0.1)',
        duration: 1.2,
        yoyo: true,
        repeat: -1,
        ease: 'sine.inOut',
      });
    } else if (state === 'synthesizing') {
      gsap.to(panel, {
        boxShadow: '0 0 25px rgba(167,139,250,0.08), 0 8px 40px rgba(0,0,0,0.6), inset 0 1px 0 rgba(167,139,250,0.05)',
        duration: 2.0,
        yoyo: true,
        repeat: -1,
        ease: 'sine.inOut',
      });
    } else if (state === 'thinking') {
      gsap.to(panel, {
        boxShadow: '0 0 30px rgba(34,211,238,0.1), 0 8px 40px rgba(0,0,0,0.6), inset 0 1px 0 rgba(34,211,238,0.08)',
        duration: 0.3,
        yoyo: true,
        repeat: -1,
        ease: 'steps(2)',
      });
    } else {
      gsap.to(panel, {
        boxShadow: '0 0 30px rgba(34,211,238,0.05), 0 8px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.03)',
        duration: 0.6,
        ease: 'power2.out',
      });
    }
  }, [state]);

  // Stop flash
  useEffect(() => {
    const prev = prevStateRef.current;
    if (prev !== 'idle' && state === 'idle') {
      setStopFlash(true);
      setTimeout(() => setStopFlash(false), 400);
    }
    prevStateRef.current = state;
  }, [state]);

  // Status color for label
  const statusColor = state === 'listening' ? '#00E5A0' : state === 'synthesizing' ? '#a78bfa' : '#22d3ee';

  return (
    <div
      ref={panelRef}
      style={{
        width: 360,
        minHeight: 480,
        background: 'linear-gradient(180deg, rgba(14, 20, 35, 0.95) 0%, rgba(8, 12, 22, 0.98) 100%)',
        backdropFilter: 'blur(30px)',
        border: `1px solid ${stopFlash ? 'rgba(255, 59, 92, 0.5)' : 'rgba(34, 211, 238, 0.1)'}`,
        borderRadius: 24,
        boxShadow: '0 0 30px rgba(34,211,238,0.05), 0 8px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.03)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '32px 28px',
        position: 'relative',
        overflow: 'hidden',
        cursor: state === 'idle' ? 'pointer' : 'default',
        transition: 'border-color 0.3s ease',
      }}
      onClick={() => state === 'idle' && onStartDemo()}
    >
      {/* Top accent line */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: '15%',
          right: '15%',
          height: 2,
          background: 'linear-gradient(90deg, transparent, rgba(34,211,238,0.4), transparent)',
          borderRadius: 1,
        }}
      />

      {/* Header - Brand */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          marginBottom: 8,
        }}
      >
        <div
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: state !== 'idle' ? statusColor : '#5A7182',
            boxShadow: state !== 'idle' ? `0 0 8px ${statusColor}` : 'none',
            transition: 'all 0.4s ease',
          }}
        />
        <span
          className="font-orbitron"
          style={{
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: '0.2em',
            color: state !== 'idle' ? 'rgba(34,211,238,0.7)' : 'rgba(90, 113, 130, 0.6)',
            transition: 'color 0.4s ease',
          }}
        >
          JARVIS
        </span>
        <div
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: state !== 'idle' ? statusColor : '#5A7182',
            boxShadow: state !== 'idle' ? `0 0 8px ${statusColor}` : 'none',
            transition: 'all 0.4s ease',
          }}
        />
      </div>

      {/* Subtitle */}
      <div
        style={{
          fontSize: 9,
          letterSpacing: '0.15em',
          color: '#3A5060',
          marginBottom: 16,
          textTransform: 'uppercase',
        }}
      >
        Voice Interface System
      </div>

      {/* Orb Core */}
      <OrbCore state={state} />

      {/* Waveform Bar */}
      <div style={{ marginTop: 12 }}>
        <WaveformBar state={state} />
      </div>

      {/* Status */}
      <div style={{ marginTop: 20 }}>
        <StatusLabel state={state} />
      </div>

      {/* Divider */}
      <div
        style={{
          width: '60%',
          height: 1,
          background: 'linear-gradient(90deg, transparent, rgba(34,211,238,0.15), transparent)',
          marginTop: 24,
          marginBottom: 20,
        }}
      />

      {/* Controls */}
      <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
        <ControlButton
          icon={<MicrophoneIcon muted={isMuted} />}
          onClick={onMuteToggle}
          active={!isMuted}
          tooltip={isMuted ? 'Unmute (M)' : 'Mute (M)'}
        />
        <ControlButton
          icon={<StopIcon />}
          onClick={onStop}
          disabled={state === 'idle'}
          variant="danger"
          tooltip="Stop (Esc)"
        />
      </div>
    </div>
  );
}
