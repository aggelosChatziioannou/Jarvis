import { useEffect, useState, useCallback, useRef } from 'react';
import { api, openStateStream } from '@/lib/api';

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'synthesizing' | 'speaking';

/**
 * Live-wired version of useVoiceState — subscribes to the daemon's
 * /ws/state WebSocket for the real voice pipeline state and sends
 * STOP / MUTE commands via the HTTP API. Falls back to a local demo
 * cycle if the daemon is unreachable (so the UI is testable even when
 * Jarvis isn't running).
 */
export function useVoiceState() {
  const [state, setState] = useState<VoiceState>('idle');
  const [isMuted, setIsMuted] = useState(false);
  const [query, setQuery] = useState<string>('');
  const [connected, setConnected] = useState(false);
  const demoTimersRef = useRef<number[]>([]);

  useEffect(() => {
    let alive = true;

    api
      .state()
      .then((s) => {
        if (!alive) return;
        setState(s.state);
        setIsMuted(s.isMuted);
        setQuery(s.query || '');
        setConnected(true);
      })
      .catch(() => {
        if (alive) setConnected(false);
      });

    const close = openStateStream((s) => {
      setState(s.state);
      setIsMuted(s.isMuted);
      setQuery(s.query || '');
      setConnected(true);
    });

    return () => {
      alive = false;
      close();
    };
  }, []);

  const clearDemoTimers = useCallback(() => {
    demoTimersRef.current.forEach((t) => window.clearTimeout(t));
    demoTimersRef.current = [];
  }, []);

  const stop = useCallback(() => {
    clearDemoTimers();
    setState('idle');
    setIsMuted(false);
    setQuery('');
    api.stop().catch(() => {
      /* still local-reset above */
    });
  }, [clearDemoTimers]);

  const toggleMute = useCallback(() => {
    if (isMuted) {
      setIsMuted(false);
      api.unmute().catch(() => {});
    } else {
      setIsMuted(true);
      clearDemoTimers();
      api.mute().catch(() => {});
    }
  }, [isMuted, clearDemoTimers]);

  /** Local-only demo cycle — only fires when the daemon is offline. */
  const startDemo = useCallback((force = false) => {
    if (!force && (connected || isMuted || state !== 'idle')) return;
    clearDemoTimers();
    setState('listening');
    const t1 = window.setTimeout(() => {
      setState('thinking');
      const t2 = window.setTimeout(() => {
        setState('speaking');
        const t3 = window.setTimeout(() => setState('idle'), 4000);
        demoTimersRef.current.push(t3);
      }, 2000);
      demoTimersRef.current.push(t2);
    }, 2000);
    demoTimersRef.current.push(t1);
  }, [clearDemoTimers, connected, isMuted, state]);

  const triggerNow = useCallback(() => {
    if (connected) {
      if (isMuted) {
        api.unmute()
          .then(() => api.triggerNow())
          .catch(() => {});
      } else {
        api.triggerNow().catch(() => {});
      }
    } else if (state === 'idle') {
      // Fallback to demo cycle when daemon is offline
      setIsMuted(false);
      startDemo(true);
    }
  }, [connected, state, isMuted, startDemo]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        e.preventDefault();
        startDemo();
      } else if (e.code === 'Escape') {
        e.preventDefault();
        stop();
      } else if (e.code === 'KeyM') {
        toggleMute();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      clearDemoTimers();
    };
  }, [startDemo, stop, toggleMute, clearDemoTimers]);

  return { state, isMuted, query, toggleMute, stop, startDemo, triggerNow };
}
