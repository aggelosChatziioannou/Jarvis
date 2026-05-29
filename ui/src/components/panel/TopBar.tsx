import { Link } from 'react-router';

function callBridge(action: 'minimize' | 'maximize' | 'close'): boolean {
  const w = window as Window & {
    consoleMinimize?: () => void;
    consoleMaximize?: () => void;
    consoleClose?: () => void;
  };
  if (action === 'minimize' && typeof w.consoleMinimize === 'function') {
    w.consoleMinimize();
    return true;
  }
  if (action === 'maximize' && typeof w.consoleMaximize === 'function') {
    w.consoleMaximize();
    return true;
  }
  if (action === 'close' && typeof w.consoleClose === 'function') {
    w.consoleClose();
    return true;
  }
  return false;
}

function WindowButton({ variant }: { variant: 'minimize' | 'maximize' | 'close' }) {
  const hoverBg = variant === 'close' ? 'rgba(252,129,129,0.15)' : 'rgba(255,255,255,0.06)';

  return (
    <button
      onClick={() => callBridge(variant)}
      title={variant.charAt(0).toUpperCase() + variant.slice(1)}
      style={{
        width: 28,
        height: 28,
        borderRadius: 6,
        background: 'transparent',
        border: 'none',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transition: 'background 0.2s',
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = hoverBg;
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
      }}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        {variant === 'minimize' && (
          <line x1="2" y1="8" x2="14" y2="8" stroke="white" strokeWidth="1" strokeLinecap="round" />
        )}
        {variant === 'maximize' && (
          <rect x="2" y="2" width="12" height="12" rx="1" stroke="white" strokeWidth="1" />
        )}
        {variant === 'close' && (
          <>
            <line x1="3" y1="3" x2="13" y2="13" stroke="#fc8181" strokeWidth="1" strokeLinecap="round" />
            <line x1="13" y1="3" x2="3" y2="13" stroke="#fc8181" strokeWidth="1" strokeLinecap="round" />
          </>
        )}
      </svg>
    </button>
  );
}

export default function TopBar() {
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest('button, a, input, [role="button"], [role="link"], [contenteditable="true"]')) return;
    const w = window as unknown as Record<string, unknown>;
    if (typeof w.consoleStartSystemMove === 'function') {
      e.preventDefault();
      (w.consoleStartSystemMove as () => void)();
    }
  };

  return (
    <div
      id="console-title-bar"
      onMouseDown={handleMouseDown}
      style={{
        height: 32,
        background: 'rgba(10, 14, 26, 0.9)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
        borderBottom: '1px solid rgba(79, 209, 197, 0.08)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 12px',
        flexShrink: 0,
        position: 'relative',
        zIndex: 10,
        userSelect: 'none',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Link
          to="/"
          style={{
            textDecoration: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <span
            className="font-orbitron"
            style={{
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: '0.18em',
              color: '#4fd1c5',
              textShadow: '0 0 8px rgba(79, 209, 197, 0.35)',
            }}
          >
            JARVIS
          </span>
        </Link>
        <span style={{ color: '#4a5568', fontSize: 10, letterSpacing: '0.05em' }}>
          // Console
        </span>
      </div>

      <div data-hide-in-native="true" style={{ display: 'flex', gap: 2 }}>
        <WindowButton variant="minimize" />
        <WindowButton variant="maximize" />
        <WindowButton variant="close" />
      </div>
    </div>
  );
}
