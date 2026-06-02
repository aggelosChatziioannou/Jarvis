export default function StatusBar() {
  return (
    <div className="h-8 shrink-0 bg-[#070a10] border-t border-white/5 flex items-center px-4 text-[11px] font-medium select-none">
      <div className="flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-[#34d399]" />
        <span className="text-[#94a3b8]">Idle</span>
      </div>
      <div className="flex-1 flex items-center justify-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-[#22d3ee]" />
        <span className="text-[#94a3b8]">Connected</span>
        <span className="text-[#475569]">·</span>
        <span className="text-[#475569] font-mono">v2.0.0-alpha</span>
      </div>
      <div className="flex items-center gap-3 text-[#475569] font-mono">
        <span>22°C</span>
        <span>2026-06-02</span>
      </div>
    </div>
  )
}
