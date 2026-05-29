import { useState } from 'react';
import type { PanelTab, TabConfig } from '@/types/panel';
import {
  ScrollText, Mic, Ear, Languages, Volume2, Brain,
  Server, Key, Database, Zap, Film,
} from 'lucide-react';

const ICON_MAP: Record<string, React.ComponentType<{ size?: number; color?: string; strokeWidth?: number }>> = {
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
  const [hovered, setHovered] = useState(false);
  const isExpanded = expanded || hovered;

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        width: isExpanded ? 180 : 48,
        background: '#0d1117',
        borderRight: '1px solid #1a2a3a',
        display: 'flex',
        flexDirection: 'column',
        transition: 'width 0.25s ease',
        overflow: 'hidden',
        flexShrink: 0,
        position: 'relative',
        zIndex: 2,
      }}
    >
      {/* Toggle / grip area */}
      <button
        onClick={onToggle}
        style={{
          width: '100%',
          height: 32,
          background: 'transparent',
          border: 'none',
          borderBottom: '1px solid rgba(26, 42, 58, 0.6)',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#4a5568',
          transition: 'color 0.2s',
          flexShrink: 0,
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = '#a0aec0'; }}
        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = '#4a5568'; }}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          style={{
            transform: isExpanded ? 'rotate(180deg)' : 'none',
            transition: 'transform 0.25s ease',
          }}
        >
          <path
            d="M4.5 2L8.5 6L4.5 10"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {/* Tab items */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
        {tabs.map(tab => {
          const isActive = tab.id === activeTab;
          const Icon = ICON_MAP[tab.icon];

          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              title={tab.label}
              style={{
                width: '100%',
                height: 40,
                background: isActive ? 'rgba(79, 209, 197, 0.08)' : 'transparent',
                border: 'none',
                borderLeft: isActive ? '2px solid #4fd1c5' : '2px solid transparent',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: isExpanded ? 10 : 0,
                padding: isExpanded ? '0 14px' : '0 0 0 14px',
                color: isActive ? '#4fd1c5' : '#4a5568',
                transition: 'all 0.2s ease',
                whiteSpace: 'nowrap',
                position: 'relative',
              }}
              onMouseEnter={e => {
                if (!isActive) {
                  (e.currentTarget as HTMLElement).style.background = 'rgba(79, 209, 197, 0.04)';
                  (e.currentTarget as HTMLElement).style.color = '#a0aec0';
                }
              }}
              onMouseLeave={e => {
                if (!isActive) {
                  (e.currentTarget as HTMLElement).style.background = 'transparent';
                  (e.currentTarget as HTMLElement).style.color = '#4a5568';
                }
              }}
            >
              <Icon size={20} color="currentColor" strokeWidth={1.5} />
              {isExpanded && (
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 400,
                    letterSpacing: '0.02em',
                    opacity: isExpanded ? 1 : 0,
                    transition: 'opacity 0.15s ease',
                  }}
                >
                  {tab.label}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Footer */}
      <div
        style={{
          padding: isExpanded ? '8px 14px' : '8px 0',
          borderTop: '1px solid rgba(26, 42, 58, 0.6)',
          fontSize: 9,
          color: '#1f2d3d',
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          textAlign: 'center',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          transition: 'all 0.25s ease',
        }}
      >
        {isExpanded ? 'v2.0.0-alpha' : 'v2'}
      </div>
    </div>
  );
}
