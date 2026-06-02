import { Home, Brain, Mic, ScrollText } from 'lucide-react'
import type { ComponentType } from 'react'

interface ItemData {
  icon: ComponentType<{ size?: number; className?: string; strokeWidth?: number }>
  label: string
  id: string
}

const items: ItemData[] = [
  { icon: Home, label: 'Dashboard', id: 'dashboard' },
  { icon: Brain, label: 'Memory', id: 'memory' },
  { icon: Mic, label: 'Audio I/O', id: 'audio' },
  { icon: ScrollText, label: 'Live Logs', id: 'logs' },
]

interface Props {
  activePage: string
  onNavigate: (page: string) => void
}

export default function Sidebar({ activePage, onNavigate }: Props) {
  return (
    <div className="w-[200px] bg-[#070a10] flex flex-col shrink-0 border-r border-white/5">
      <nav className="flex-1 py-2">
        {items.map((item) => {
          const isActive = item.id === activePage
          const Icon = item.icon
          return (
            <div key={item.id} className="relative">
              {isActive && <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-[#22d3ee]" />}
              <button
                onClick={() => onNavigate(item.id)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors duration-150 ${
                  isActive ? 'bg-[#22d3ee]/5 text-[#22d3ee]' : 'text-[#475569] hover:text-[#94a3b8] hover:bg-white/[0.03]'
                }`}
              >
                <Icon size={18} className={isActive ? 'text-[#22d3ee]' : ''} strokeWidth={isActive ? 2 : 1.5} />
                <span className="text-[13px] font-medium">{item.label}</span>
              </button>
            </div>
          )
        })}
      </nav>
    </div>
  )
}
