import React, { useState, useRef } from 'react';

const ToggleSwitch = React.memo(function ToggleSwitch({ checked, onChange, label }: {
  checked: boolean; onChange: (val: boolean) => void; label: string;
}) {
  return (
    <button onClick={() => onChange(!checked)} className="flex items-center gap-2 group cursor-pointer"
      aria-label={label} role="switch" aria-checked={checked}>
      <span className="text-[11px] text-[#475569] group-hover:text-[#94a3b8] transition-colors">{label}</span>
      <div className={`relative w-8 h-[18px] rounded-full transition-colors duration-150 border ${
        checked ? 'bg-[#22d3ee] border-[#22d3ee]' : 'bg-[#1e293b] border-[#475569]'
      }`}>
        <div className={`absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white transition-transform duration-150 ${
          checked ? 'translate-x-[14px]' : 'translate-x-[2px]'
        }`} />
      </div>
    </button>
  );
});

const SearchInput = React.memo(function SearchInput({ value, onChange }: {
  value: string; onChange: (val: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [focused, setFocused] = useState(false);
  return (
    <div className={`relative flex items-center h-8 px-3 rounded-lg transition-all duration-150 border ${
      focused
        ? 'shadow-[inset_0_0_0_1px_rgba(34,211,238,0.15)] border-[#22d3ee]/30'
        : 'border-white/5'
    }`}
      style={{ width: '100%', maxWidth: 170, minWidth: 110, backgroundColor: 'rgba(15, 23, 42, 0.6)' }}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[#475569] shrink-0 mr-2">
        <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
      <input ref={inputRef} type="text" value={value} onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
        placeholder="Search memories..."
        className="w-full bg-transparent border-none outline-none text-[13px] text-[#f8fafc] placeholder:text-[#475569]" />
      {value && (
        <button onClick={() => { onChange(''); inputRef.current?.focus(); }}
          className="ml-1 text-[#475569] hover:text-[#f8fafc] transition-colors shrink-0" aria-label="Clear search">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  );
});

export default function GraphHeader({ totalNodes, searchQuery, onSearchChange, showEmphasis, onToggleEmphasis, zoom, onZoomIn, onZoomOut, onResetView }: {
  totalNodes: number; searchQuery: string; onSearchChange: (query: string) => void;
  showEmphasis: boolean; onToggleEmphasis: (val: boolean) => void;
  zoom: number; onZoomIn: () => void; onZoomOut: () => void; onResetView: () => void;
}) {
  return (
    <div className="absolute top-0 left-0 right-0 z-20 pointer-events-none"
      style={{ height: 64, background: 'linear-gradient(to bottom, rgba(10, 14, 23, 0.92) 0%, rgba(10, 14, 23, 0.7) 60%, rgba(10, 14, 23, 0) 100%)' }}>
      <div className="flex items-center h-12 px-4 gap-4 min-w-0">
        {/* Left: Title + counter */}
        <div className="flex items-center gap-3 pointer-events-auto shrink-0">
          <span className="text-[#475569] font-mono text-[11px] tracking-[0.08em] uppercase whitespace-nowrap">MEMORY GRAPH</span>
          <span className="px-2 py-0.5 rounded-full border border-white/5 text-[#475569] text-[11px] font-mono whitespace-nowrap"
            style={{ backgroundColor: 'rgba(15, 23, 42, 0.6)' }}>
            {totalNodes} NODES
          </span>
        </div>

        {/* Center: Search */}
        <div className="flex-1 flex justify-center pointer-events-auto min-w-0">
          <SearchInput value={searchQuery} onChange={onSearchChange} />
        </div>

        {/* Right: Emphasis + Zoom */}
        <div className="flex items-center gap-3 pointer-events-auto shrink-0">
          <ToggleSwitch checked={showEmphasis} onChange={onToggleEmphasis} label="Emphasis" />
          <div className="flex items-center gap-1">
            <button onClick={onZoomOut}
              className="w-7 h-7 rounded-md flex items-center justify-center border border-white/5 hover:border-white/10 hover:bg-white/5 transition-all duration-150 cursor-pointer"
              style={{ backgroundColor: 'rgba(15, 23, 42, 0.6)' }} aria-label="Zoom out">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="5" y1="12" x2="19" y2="12" /></svg>
            </button>
            <span className="text-[#475569] text-[11px] font-mono w-10 text-center">{Math.round((zoom / 0.8) * 100)}%</span>
            <button onClick={onZoomIn}
              className="w-7 h-7 rounded-md flex items-center justify-center border border-white/5 hover:border-white/10 hover:bg-white/5 transition-all duration-150 cursor-pointer"
              style={{ backgroundColor: 'rgba(15, 23, 42, 0.6)' }} aria-label="Zoom in">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
            </button>
            <button onClick={onResetView}
              className="w-7 h-7 rounded-md flex items-center justify-center border border-white/5 hover:border-white/10 hover:bg-white/5 transition-all duration-150 cursor-pointer"
              style={{ backgroundColor: 'rgba(15, 23, 42, 0.6)' }} aria-label="Reset view" title="Reset view">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" /><line x1="12" y1="1" x2="12" y2="5" /><line x1="12" y1="19" x2="12" y2="23" />
                <line x1="1" y1="12" x2="5" y2="12" /><line x1="19" y1="12" x2="23" y2="12" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
