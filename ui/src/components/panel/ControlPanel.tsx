import { useState, useCallback } from 'react';
import type { PanelTab } from '@/types/panel';
import { TABS } from '@/types/panel';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import StatusBar from './StatusBar';
import LiveLogsTab from './tabs/LiveLogsTab';
import AudioIOTab from './tabs/AudioIOTab';
import WakeWordTab from './tabs/WakeWordTab';
import VoiceTTSTab from './tabs/VoiceTTSTab';
import LanguageModelTab from './tabs/LanguageModelTab';
import MCPServersTab from './tabs/MCPServersTab';
import APIKeysTab from './tabs/APIKeysTab';
import EasterEggsTab from './tabs/EasterEggsTab';

const TAB_COMPONENTS: Record<PanelTab, React.ComponentType> = {
  'live-logs': LiveLogsTab,
  'audio-io': AudioIOTab,
  'wake-word': WakeWordTab,
  'voice-tts': VoiceTTSTab,
  'language-model': LanguageModelTab,
  'mcp-servers': MCPServersTab,
  'api-keys': APIKeysTab,
  'easter-eggs': EasterEggsTab,
};

export default function ControlPanel() {
  const [activeTab, setActiveTab] = useState<PanelTab>('live-logs');
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  const toggleSidebar = useCallback(() => {
    setSidebarExpanded(prev => !prev);
  }, []);

  const ActiveComponent = TAB_COMPONENTS[activeTab];

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        background: '#060a12',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        fontFamily: "'Inter', sans-serif",
        position: 'relative',
      }}
    >
      {/* Subtle hex grid watermark */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 0l25.98 15v30L30 60 4.02 45V15L30 0z' fill='none' stroke='%234fd1c5' stroke-opacity='0.015'/%3E%3C/svg%3E")`,
          backgroundSize: 60,
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      {/* Top Bar */}
      <TopBar />

      {/* Main Content */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', position: 'relative', zIndex: 1 }}>
        {/* Sidebar */}
        <Sidebar
          tabs={TABS}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          expanded={sidebarExpanded}
          onToggle={toggleSidebar}
        />

        {/* Content Area */}
        <div
          style={{
            flex: 1,
            overflow: 'auto',
            padding: '12px 16px',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* Tab Header */}
          <div style={{ marginBottom: 16, flexShrink: 0 }}>
            <h1
              style={{
                fontFamily: "'Orbitron', sans-serif",
                fontSize: 13,
                fontWeight: 500,
                letterSpacing: '0.12em',
                color: '#e6f1ff',
                textTransform: 'uppercase',
                marginBottom: 4,
              }}
            >
              {TABS.find(t => t.id === activeTab)?.label}
            </h1>
            <div
              style={{
                width: 40,
                height: 2,
                background: 'linear-gradient(90deg, #4fd1c5, transparent)',
                borderRadius: 1,
              }}
            />
          </div>

          {/* Tab Content */}
          <div
            style={{
              flex: 1,
              background: 'rgba(6, 10, 18, 0.6)',
              border: '1px solid rgba(79, 209, 197, 0.08)',
              borderRadius: 6,
              padding: 20,
              overflow: 'auto',
            }}
          >
            <ActiveComponent />
          </div>
        </div>
      </div>

      {/* Status Bar */}
      <StatusBar />
    </div>
  );
}
