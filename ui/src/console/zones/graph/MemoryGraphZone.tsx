import React, { useState, useCallback, useRef, useEffect, memo } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { categories } from '@/console/data/graphMock';
import { useMemoryDataCtx } from '@/console/services/MemoryDataContext';
import { useGraphLayout } from './useGraphLayout';
import type { GraphLayoutNode } from './useGraphLayout';
import { useZoomPan } from './useZoomPan';
import GraphNode from './GraphNode';
import ConnectionLine from './ConnectionLine';
import GraphHeader from './GraphHeader';
import ClusterPanel from './ClusterPanel';
import gsap from 'gsap';

const ZoneHexGrid = memo(function ZoneHexGrid() {
  const hexPath = React.useMemo(() => {
    const r = 25;
    const pts: string[] = [];
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 180) * (60 * i - 30);
      pts.push(`${r * Math.cos(angle)},${r * Math.sin(angle)}`);
    }
    return `M${pts.join('L')}Z`;
  }, []);
  return (
    <div className="absolute inset-0 pointer-events-none" aria-hidden="true">
      <svg width="100%" height="100%" style={{ opacity: 0.03 }}>
        <defs>
          <pattern id="hex-pattern-zone" width="50" height="43.3" patternUnits="userSpaceOnUse" patternTransform="translate(25, 21.65)">
            <path d={hexPath} fill="none" stroke="#475569" strokeWidth="0.4" transform="translate(25, 21.65)" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#hex-pattern-zone)" />
      </svg>
    </div>
  );
});

const ZoneParticles = memo(function ZoneParticles() {
  const particles = React.useMemo(() => {
    const pts: Array<{ id: number; x: number; y: number; size: number; opacity: number; duration: number; delay: number; driftX: number; driftY: number }> = [];
    for (let i = 0; i < 15; i++) {
      const angle = Math.random() * Math.PI * 2;
      const dist = Math.sqrt(Math.random()) * 0.45;
      pts.push({
        id: i, x: 50 + Math.cos(angle) * dist * 100, y: 50 + Math.sin(angle) * dist * 100,
        size: 1.5 + Math.random() * 2.5, opacity: 0.08 + Math.random() * 0.12,
        duration: 25 + Math.random() * 20, delay: Math.random() * -45,
        driftX: (Math.random() - 0.5) * 150, driftY: (Math.random() - 0.5) * 150,
      });
    }
    return pts;
  }, []);
  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
      {particles.map((p) => (
        <div key={p.id} className="absolute rounded-full bg-[#22d3ee] animate-particle-drift"
          style={{
            left: `${p.x}%`, top: `${p.y}%`, width: p.size, height: p.size, opacity: p.opacity,
            ['--drift-x' as string]: `${p.driftX}px`, ['--drift-y' as string]: `${p.driftY}px`,
            ['--drift-duration' as string]: `${p.duration}s`, animationDelay: `${p.delay}s`,
          }}
        />
      ))}
    </div>
  );
});

const ZoneAmbientGlow = memo(function ZoneAmbientGlow() {
  return (
    <div className="absolute pointer-events-none animate-glow-pulse"
      style={{
        width: 300, height: 300, left: '50%', top: '50%', transform: 'translate(-50%, -50%)',
        borderRadius: '50%', background: 'radial-gradient(circle, rgba(34, 211, 238, 0.06) 0%, transparent 70%)',
      }}
      aria-hidden="true"
    />
  );
});

const ZoneVignette = memo(function ZoneVignette() {
  return (
    <div className="absolute inset-0 pointer-events-none"
      style={{
        background: 'radial-gradient(circle at center, transparent 25%, rgba(10, 14, 23, 0.65) 100%)',
      }}
      aria-hidden="true"
    />
  );
});

// Hubs start open so the constellation greets you; clusters bloom on click.
const DEFAULT_EXPANDED = ['cat-identity', 'cat-directives', 'cat-events', 'cat-preferences', 'cat-health'];

export default function MemoryGraphZone({
  selectedNodeId,
  onNodeSelect,
}: {
  selectedNodeId: string | null;
  onNodeSelect: (id: string | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [showEmphasis, setShowEmphasis] = useState(false);
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set(DEFAULT_EXPANDED));
  const allCategories = React.useMemo(() => new Set(categories.map((c) => c.type)), []);

  const {
    zoom, panX, panY, isPanning,
    handleWheel, handleMouseDown, handleMouseMove, handleMouseUp, handleMouseLeave, handleDoubleClick,
    zoomIn, zoomOut, resetView,
  } = useZoomPan(containerRef);

  const { graphNodes, saveNodeData, deleteNode } = useMemoryDataCtx();
  const { nodes, connections } = useGraphLayout({
    searchQuery, visibleCategories: allCategories, showEmphasis, nodes: graphNodes, expandedIds,
  });
  const totalFacts = nodes.filter((n) => n.type === 'memory').length;

  useEffect(() => {
    if (containerRef.current) {
      gsap.fromTo(containerRef.current, { opacity: 0 }, { opacity: 1, duration: 0.6, delay: 0.3, ease: 'power2.out' });
    }
  }, []);

  const toggleExpanded = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleNodeClick = useCallback((node: GraphLayoutNode) => {
    if (node.type === 'category' || node.type === 'cluster') {
      // Toggle the subtree; opening also surfaces the cluster overview panel.
      const opening = !expandedIds.has(node.id);
      toggleExpanded(node.id);
      setSelectedClusterId(opening ? node.id : (selectedClusterId === node.id ? null : selectedClusterId));
    } else if (node.type === 'memory') {
      setSelectedClusterId(null);
      onNodeSelect(node.id === selectedNodeId ? null : node.id);
    } else {
      setSelectedClusterId(null);
      resetView();
    }
  }, [onNodeSelect, selectedNodeId, selectedClusterId, expandedIds, toggleExpanded, resetView]);

  const handleCloseCluster = useCallback(() => {
    setSelectedClusterId(null);
  }, []);

  const handleSaveMemory = useCallback((id: string, value: string) => {
    void saveNodeData(id, value);
  }, [saveNodeData]);

  const handleDeleteMemory = useCallback((id: string) => {
    void deleteNode(id);
  }, [deleteNode]);

  const handleBackgroundClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if ((target.tagName === 'svg' || target.closest('svg') === svgRef.current) && !(target.closest?.('[data-node]'))) {
      setSelectedClusterId(null);
      onNodeSelect(null);
    }
  }, [onNodeSelect]);

  const graphTransform = React.useMemo(() => `translate(${panX}, ${panY}) scale(${zoom})`, [panX, panY, zoom]);

  const visibleConnections = React.useMemo(() => connections.filter((c) => c.visible), [connections]);
  const visibleNodes = React.useMemo(() => nodes.filter((n) => n.visible), [nodes]);

  return (
    <div ref={containerRef}
      className={`relative flex-1 h-full overflow-hidden ${isPanning ? 'cursor-grabbing' : 'cursor-grab'}`}
      onWheel={handleWheel} onMouseDown={handleMouseDown} onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp} onMouseLeave={handleMouseLeave} onDoubleClick={handleDoubleClick}
      onClick={handleBackgroundClick}>
      <ZoneHexGrid />
      <ZoneAmbientGlow />
      <ZoneParticles />
      <ZoneVignette />
      <svg ref={svgRef} width="100%" height="100%" className="absolute inset-0" style={{ zIndex: 10 }}>
        <g transform={graphTransform}>
          <AnimatePresence>
            {visibleConnections.map((conn) => (
              <motion.g key={conn.id}
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}>
                <ConnectionLine connection={conn} selectedNodeId={selectedNodeId} />
              </motion.g>
            ))}
          </AnimatePresence>
          <AnimatePresence>
            {visibleNodes.map((node) => (
              <motion.g key={node.id}
                initial={{ opacity: 0, scale: 0.3 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.3 }}
                transition={{ duration: 0.35, delay: node.type === 'memory' ? (node.entranceDelay % 400) / 1000 : 0, ease: [0.34, 1.56, 0.64, 1] }}
                style={{ transformOrigin: `${node.computedX}px ${node.computedY}px` }}>
                <GraphNode node={node} isSelected={node.id === selectedNodeId}
                  emphasisMode={showEmphasis} selectedNodeId={selectedNodeId} onClick={handleNodeClick} />
              </motion.g>
            ))}
          </AnimatePresence>
        </g>
      </svg>
      <GraphHeader totalNodes={totalFacts} searchQuery={searchQuery} onSearchChange={setSearchQuery}
        showEmphasis={showEmphasis} onToggleEmphasis={setShowEmphasis}
        zoom={zoom} onZoomIn={zoomIn} onZoomOut={zoomOut} onResetView={resetView} />

      {/* Cluster Info Panel — real per-fact edit + delete */}
      <ClusterPanel
        categoryNode={nodes.find((n) => n.id === selectedClusterId) ?? null}
        allNodes={nodes}
        onSaveMemory={handleSaveMemory}
        onDeleteMemory={handleDeleteMemory}
        onClose={handleCloseCluster}
      />
    </div>
  );
}
