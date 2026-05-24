interface ToggleSwitchProps {
  enabled: boolean;
  onChange: (v: boolean) => void;
}

export default function ToggleSwitch({ enabled, onChange }: ToggleSwitchProps) {
  return (
    <button
      onClick={() => onChange(!enabled)}
      style={{
        width: 44,
        height: 24,
        borderRadius: 12,
        background: enabled ? 'rgba(34, 211, 238, 0.3)' : 'rgba(255, 255, 255, 0.08)',
        border: `1px solid ${enabled ? 'rgba(34, 211, 238, 0.5)' : 'rgba(255, 255, 255, 0.1)'}`,
        cursor: 'pointer',
        position: 'relative',
        transition: 'all 0.3s ease',
        padding: 0,
      }}
    >
      <div
        style={{
          width: 18,
          height: 18,
          borderRadius: '50%',
          background: enabled ? '#22d3ee' : '#5A7182',
          position: 'absolute',
          top: 2,
          left: enabled ? 22 : 2,
          transition: 'all 0.3s ease',
          boxShadow: enabled ? '0 0 8px rgba(34, 211, 238, 0.5)' : 'none',
        }}
      />
    </button>
  );
}
