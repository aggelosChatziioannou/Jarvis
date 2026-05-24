import { useVoiceState } from '@/hooks/useVoiceState';
import JarvisCard from '@/components/JarvisCard';

/**
 * Home page = just the floating Jarvis card.
 * No surrounding gradient, no hint text, no Console link — the card is
 * the only thing the user sees. The page background is transparent so
 * the PyQt frameless container can render only the card itself.
 */
export default function Home() {
  const { state, isMuted, toggleMute, stop, startDemo } = useVoiceState();

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
      <JarvisCard
        state={state}
        isMuted={isMuted}
        onMuteToggle={toggleMute}
        onStop={stop}
        onStartDemo={startDemo}
      />
    </div>
  );
}
