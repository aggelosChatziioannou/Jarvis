import type { PanelTab, TabConfig } from '@/types/panel';
import {
  ScrollText, Mic, Ear, Languages, Volume2, Brain,
  Server, Key, Database, Zap, Film, ChevronLeft, ChevronRight
} from 'lucide-react';

const ICON_MAP: Record<string, React.ComponentType<{ size?: number; color?: string }>> = {
  ScrollText, Mic, Ear, Languages, Volume2, Brain,
  Server, Key, Database, Zap, Film,
};

interface SidebarProps {
  tabs: TabConfig[];
  activeTab: PanelTab;
  onTabChange: (tab: PanelTab) => void;
  expanded: boolean;
  onToggle: () => void;
}

export default function Sidebar({ tabs, activeTab, onTabChange, expanded, onToggle }: SidebarProps) {
  return (
    <div
      style={{
        width: expanded ? 220 : 64,
        background: 'rgba(8, 14, 28, 0.85)',
        borderRight: '1px solid rgba(34, 211, 238, 0.08)',
        display: 'flex',
        flexDirection: 'column',
        transition: 'width 0.3s ease',
        overflow: 'hidden',
        flexShrink: 0,
        position: 'relative',
        zIndex: 2,
      }}
    >
      {/* Toggle button */}
      <button
        onClick={onToggle}
        style={{
          width: '100%',
          height: 40,
          background: 'transparent',
          border: 'none',
          borderBottom: '1px solid rgba(34, 211, 238, 0.06)',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#7dd3fc',
          transition: 'background 0.2s',
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(34, 211, 238, 0.05)'; }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
      >
        {expanded ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}
      </button>

      {/* Tab items */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
        {tabs.map(tab => {
          const isActive = tab.id === activeTab;
          const Icon = ICON_MAP[tab.icon];

          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              style={{
                width: '100%',
                height: 44,
                background: isActive ? 'rgba(34, 211, 238, 0.08)' : 'transparent',
                border: 'none',
                borderLeft: isActive ? '3px solid #22d3ee' : '3px solid transparent',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: expanded ? 12 : 0,
                padding: expanded ? '0 16px' : '0 0 0 20px',
                color: isActive ? '#22d3ee' : 'rgba(125, 211, 252, 0.5)',
                transition: 'all 0.2s ease',
                whiteSpace: 'nowrap',
                position: 'relative',
              }}
              onMouseEnter={e => {
                if (!isActive) {
                  (e.currentTarget as HTMLElement).style.background = 'rgba(34, 211, 238, 0.04)';
                  (e.currentTarget as HTMLElement).style.color = '#7dd3fc';
                }
              }}
              onMouseLeave={e => {
                if (!isActive) {
                  (e.currentTarget as HTMLElement).style.background = 'transparent';
                  (e.currentTarget as HTMLElement).style.color = 'rgba(125, 211, 252, 0.5)';
                }
              }}
            >
              {isActive && (
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: 3,
                    background: '#22d3ee',
                    boxShadow: '0 0 10px rgba(34, 211, 238, 0.5)',
                    borderRadius: '0 2px 2px 0',
                  }}
                />
              )}
              <Icon size={20} />
              {expanded && (
                <span style={{ fontSize: 13, fontWeight: 400, letterSpacing: '0.02em' }}>
                  {tab.label}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Footer */}
      {expanded && (
        <div
          style={{
            padding: '12px 16px',
            borderTop: '1px solid rgba(34, 211, 238, 0.06)',
            fontSize: 10,
            color: 'rgba(125, 211, 252, 0.25)',
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
          }}
        >
          v2.0.0-alpha
        </div>
      )}
    </div>
  );
}
