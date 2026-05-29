import { useState, useCallback } from 'react';
import { useVoiceState } from '@/hooks/useVoiceState';
import { useBootSequence } from '@/hooks/useBootSequence';
import JarvisCard from '@/components/JarvisCard';
import BootScreen from '@/components/BootScreen';

/**
 * Home page — floating Jarvis card with cinematic boot sequence.
 *
 * On first mount we show BootScreen while probing real daemon subsystems.
 * Once the sequence completes (instantly if the daemon is already fully up),
 * a glitch transition swaps the boot overlay for the live JarvisCard.
 */
export default function Home() {
  const { state, isMuted, query, toggleMute, stop, startDemo, triggerNow } = useVoiceState();
  const [bootFinished, setBootFinished] = useState(false);

  const { stages, activeStageIndex, progress, isComplete } = useBootSequence(
    !bootFinished
  );

  const handleBootTransitionComplete = useCallback(() => {
    setBootFinished(true);
  }, []);

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {!bootFinished && (
        <BootScreen
          stages={stages}
          activeStageIndex={activeStageIndex}
          progress={progress}
          isComplete={isComplete}
          onTransitionComplete={handleBootTransitionComplete}
        />
      )}

      {bootFinished && (
        <JarvisCard
          state={state}
          isMuted={isMuted}
          query={query}
          onMuteToggle={toggleMute}
          onStop={stop}
          onStartDemo={startDemo}
          onTriggerNow={triggerNow}
        />
      )}
    </div>
  );
}
