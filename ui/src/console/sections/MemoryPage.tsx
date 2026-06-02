import { useState, useCallback } from 'react';
import Zone1MemoryCore from '@/console/zones/Zone1MemoryCore';
import Zone2Timeline from '@/console/zones/Zone2Timeline';
import Zone3DetailPanel from '@/console/zones/Zone3DetailPanel';
import type { GraphNode, Reminder } from '@/console/types';
import { sampleNodes } from '@/console/data/demo';

export default function MemoryPage() {
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedReminder, setSelectedReminder] = useState<Reminder | null>(null);
  const [zone2Collapsed, setZone2Collapsed] = useState(false);
  const [zone3Collapsed, setZone3Collapsed] = useState(false);

  const selectedNodeId = selectedNode?.id ?? null;

  const handleNodeSelectById = useCallback((id: string | null) => {
    if (id === null) {
      setSelectedNode(null);
      return;
    }
    const node = sampleNodes.find((n) => n.id === id) ?? null;
    setSelectedNode(node);
    setSelectedReminder(null);
  }, []);

  const handleReminderSelect = useCallback((reminder: Reminder | null) => {
    setSelectedReminder(reminder);
    setSelectedNode(null);
  }, []);

  // Calculate flex ratios based on which zones are collapsed
  const getZone1Flex = () => {
    if (zone2Collapsed && zone3Collapsed) return 100;
    if (zone2Collapsed || zone3Collapsed) return 72;
    return 53;
  };

  return (
    <div className="flex gap-3 h-full">
      {/* Zone 1: Memory Graph */}
      <div
        className="min-w-0 transition-all duration-300 ease-out"
        style={{ flex: `${getZone1Flex()}` }}
      >
        <Zone1MemoryCore
          selectedNodeId={selectedNodeId}
          onNodeSelect={handleNodeSelectById}
        />
      </div>

      {/* Zone 2: Timeline — collapsible */}
      <div
        className="transition-all duration-300 ease-out"
        style={{
          flex: zone2Collapsed ? '0 0 48px' : '0 0 25%',
          maxWidth: zone2Collapsed ? '48px' : '25%',
          minWidth: zone2Collapsed ? '48px' : '200px',
        }}
      >
        <Zone2Timeline
          onReminderSelect={handleReminderSelect}
          selectedReminder={selectedReminder}
          collapsed={zone2Collapsed}
          onToggleCollapse={() => setZone2Collapsed(!zone2Collapsed)}
        />
      </div>

      {/* Zone 3: Detail Panel — collapsible */}
      <div
        className="transition-all duration-300 ease-out"
        style={{
          flex: zone3Collapsed ? '0 0 48px' : '0 0 20%',
          maxWidth: zone3Collapsed ? '48px' : '20%',
          minWidth: zone3Collapsed ? '48px' : '180px',
        }}
      >
        <Zone3DetailPanel
          selectedNode={selectedNode}
          selectedReminder={selectedReminder}
          collapsed={zone3Collapsed}
          onToggleCollapse={() => setZone3Collapsed(!zone3Collapsed)}
          onNodeSelect={setSelectedNode}
        />
      </div>
    </div>
  );
}
