interface ToggleSwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
}

export default function ToggleSwitch({ checked, onChange, label }: ToggleSwitchProps) {
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer select-none">
      <div
        className={`
          relative w-9 h-5 rounded-full transition-colors duration-200
          ${checked ? 'bg-[#22d3ee]' : 'bg-[#334155]'}
        `}
        onClick={() => onChange(!checked)}
      >
        <div
          className={`
            absolute top-0.5 w-4 h-4 rounded-full bg-white shadow
            transition-transform duration-200
            ${checked ? 'translate-x-4.5 left-0' : 'left-0.5'}
          `}
          style={{ transform: checked ? 'translateX(16px)' : 'translateX(0)' }}
        />
      </div>
      {label && (
        <span className="text-xs text-[#94a3b8]">{label}</span>
      )}
    </label>
  );
}
