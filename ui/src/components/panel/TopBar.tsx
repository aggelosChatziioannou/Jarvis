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
  const colors = {
    minimize: '#7dd3fc',
    maximize: '#7dd3fc',
    close: '#f87171',
  };

  const icons = {
    minimize: <rect x="4" y="11" width="12" height="2" rx="1" fill={colors.minimize} />,
    maximize: (
      <rect x="3" y="3" width="14" height="14" rx="2" stroke={colors.maximize} strokeWidth="1.5" fill="none" />
    ),
    close: (
      <>
        <line x1="5" y1="5" x2="15" y2="15" stroke={colors.close} strokeWidth="1.5" strokeLinecap="round" />
        <line x1="15" y1="5" x2="5" y2="15" stroke={colors.close} strokeWidth="1.5" strokeLinecap="round" />
      </>
    ),
  };

  return (
    <button
      onClick={() => callBridge(variant)}
      title={variant.charAt(0).toUpperCase() + variant.slice(1)}
      style={{
        width: 32,
        height: 32,
        borderRadius: 8,
        background: 'transparent',
        border: 'none',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transition: 'background 0.2s',
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background =
          variant === 'close' ? 'rgba(248, 113, 113, 0.12)' : 'rgba(255,255,255,0.05)';
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
      }}
    >
      <svg width="20" height="20" viewBox="0 0 20 20">
        {icons[variant]}
      </svg>
    </button>
  );
}

export default function TopBar() {
  return (
    <div
      id="native-hide-window-controls"
      style={{
        height: 48,
        background: 'rgba(8, 14, 28, 0.9)',
        borderBottom: '1px solid rgba(34, 211, 238, 0.08)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        flexShrink: 0,
        position: 'relative',
        zIndex: 2,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Link
          to="/"
          style={{
            textDecoration: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span
            className="font-orbitron"
            style={{
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: '0.2em',
              color: '#22d3ee',
            }}
          >
            JARVIS
          </span>
        </Link>
        <span style={{ color: 'rgba(125, 211, 252, 0.3)', fontSize: 12 }}>·</span>
        <span
          style={{
            fontSize: 12,
            color: '#7dd3fc',
            letterSpacing: '0.04em',
          }}
        >
          Control Console
        </span>
      </div>

      {/* Right: Window controls — hidden in native Qt host via injected CSS */}
      <div data-hide-in-native="true" style={{ display: 'flex', gap: 4 }}>
        <WindowButton variant="minimize" />
        <WindowButton variant="maximize" />
        <WindowButton variant="close" />
      </div>
    </div>
  );
}
