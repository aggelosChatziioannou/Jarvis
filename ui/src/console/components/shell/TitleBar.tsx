interface Props { pageTitle: string }

export default function TitleBar({ pageTitle }: Props) {
  return (
    <div className="h-10 shrink-0 bg-[#070a10] border-b border-white/5 flex items-center px-4 select-none">
      <span className="text-[11px] font-semibold tracking-widest text-[#475569]">
        JARVIS <span className="text-[#22d3ee]">//</span> CONSOLE
      </span>
      <span className="flex-1 text-center text-[11px] font-semibold tracking-widest text-[#22d3ee] uppercase">
        {pageTitle}
      </span>
      <span className="w-[120px]" />
    </div>
  )
}
