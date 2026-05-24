import { useState, type ReactNode } from 'react';

interface ControlButtonProps {
  icon: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
  variant?: 'default' | 'danger';
  tooltip?: string;
}

export default function ControlButton({
  icon,
  onClick,
  disabled = false,
  active = false,
  variant = 'default',
  tooltip,
}: ControlButtonProps) {
  const [hovered, setHovered] = useState(false);

  const isDanger = variant === 'danger';
  const bgNormal = 'rgba(255, 255, 255, 0.04)';
  const bgHover = isDanger ? 'rgba(255, 59, 92, 0.1)' : 'rgba(0, 212, 255, 0.1)';
  const borderNormal = 'rgba(255, 255, 255, 0.06)';
  const borderHover = isDanger ? 'rgba(255, 59, 92, 0.3)' : 'rgba(0, 212, 255, 0.2)';

  return (
    <div style={{ position: 'relative' }}>
      {/* Tooltip */}
      {hovered && tooltip && !disabled && (
        <div
          style={{
            position: 'absolute',
            bottom: 'calc(100% + 8px)',
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'rgba(8, 16, 30, 0.95)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: 6,
            padding: '4px 10px',
            fontSize: 11,
            fontFamily: "'Inter', sans-serif",
            color: '#E8F4F8',
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
            animation: 'tooltipFadeIn 0.2s ease forwards',
            zIndex: 10,
          }}
        >
          {tooltip}
        </div>
      )}

      <button
        onClick={onClick}
        disabled={disabled}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          width: 44,
          height: 44,
          borderRadius: 12,
          background: hovered && !disabled ? bgHover : bgNormal,
          border: `1px solid ${hovered && !disabled ? borderHover : borderNormal}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.3 : 1,
          pointerEvents: disabled ? 'none' : 'auto',
          transition: 'all 0.2s ease',
          position: 'relative',
          color: active ? '#E8F4F8' : '#5A7182',
        }}
      >
        {icon}

        {/* Active indicator dot */}
        {active && (
          <span
            style={{
              position: 'absolute',
              top: 4,
              right: 4,
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: '#00E5A0',
              boxShadow: '0 0 6px rgba(0, 229, 160, 0.6)',
            }}
          />
        )}
      </button>
    </div>
  );
}
