import { useState, useCallback } from 'react';
import type { PanelTab } from '@/types/panel';
import { TABS } from '@/types/panel';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import LiveLogsTab from './tabs/LiveLogsTab';
import AudioIOTab from './tabs/AudioIOTab';
import WakeWordTab from './tabs/WakeWordTab';
import TranscriptionTab from './tabs/TranscriptionTab';
import VoiceTTSTab from './tabs/VoiceTTSTab';
import LanguageModelTab from './tabs/LanguageModelTab';
import MCPServersTab from './tabs/MCPServersTab';
import APIKeysTab from './tabs/APIKeysTab';
import MemoryTab from './tabs/MemoryTab';
import FastPathsTab from './tabs/FastPathsTab';
import EasterEggsTab from './tabs/EasterEggsTab';

const TAB_COMPONENTS: Record<PanelTab, React.ComponentType> = {
  'live-logs': LiveLogsTab,
  'audio-io': AudioIOTab,
  'wake-word': WakeWordTab,
  'transcription': TranscriptionTab,
  'voice-tts': VoiceTTSTab,
  'language-model': LanguageModelTab,
  'mcp-servers': MCPServersTab,
  'api-keys': APIKeysTab,
  'memory': MemoryTab,
  'fast-paths': FastPathsTab,
  'easter-eggs': EasterEggsTab,
};

export default function ControlPanel() {
  const [activeTab, setActiveTab] = useState<PanelTab>('live-logs');
  const [sidebarExpanded, setSidebarExpanded] = useState(true);

  const toggleSidebar = useCallback(() => {
    setSidebarExpanded(prev => !prev);
  }, []);

  const ActiveComponent = TAB_COMPONENTS[activeTab];

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        background: 'linear-gradient(180deg, #050b1f 0%, #0a1428 100%)',
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
          backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 0l25.98 15v30L30 60 4.02 45V15L30 0z' fill='none' stroke='%2322d3ee' stroke-opacity='0.02'/%3E%3C/svg%3E")`,
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
            padding: 24,
          }}
        >
          {/* Tab Header */}
          <div style={{ marginBottom: 20 }}>
            <h1
              style={{
                fontFamily: "'Orbitron', sans-serif",
                fontSize: 14,
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
                background: 'linear-gradient(90deg, #22d3ee, transparent)',
                borderRadius: 1,
              }}
            />
          </div>

          {/* Tab Content */}
          <div
            style={{
              background: 'rgba(15, 26, 46, 0.6)',
              border: '1px solid rgba(34, 211, 238, 0.12)',
              borderRadius: 16,
              padding: 24,
              minHeight: 'calc(100vh - 180px)',
            }}
          >
            <ActiveComponent />
          </div>
        </div>
      </div>
    </div>
  );
}
