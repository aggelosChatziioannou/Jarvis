import React, { useState, useCallback, useRef, useEffect, memo } from 'react';
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
  // Editable memory overrides
  const [memoryOverrides, setMemoryOverrides] = useState<Record<string, { value: string; importance: number; permanent: boolean }>>({});
  // All categories always visible — no filter chips needed
  const allCategories = React.useMemo(() => new Set(categories.map((c) => c.type)), []);

  const {
    zoom, panX, panY, isPanning,
    handleWheel, handleMouseDown, handleMouseMove, handleMouseUp, handleMouseLeave, handleDoubleClick,
    zoomIn, zoomOut, resetView,
  } = useZoomPan(containerRef);

  const { graphNodes } = useMemoryDataCtx();
  const { nodes, connections } = useGraphLayout({ searchQuery, visibleCategories: allCategories, showEmphasis, nodes: graphNodes });
  const visibleMemoryCount = nodes.filter((n) => n.type === 'memory' && n.visible).length;

  useEffect(() => {
    if (containerRef.current) {
      gsap.fromTo(containerRef.current, { opacity: 0 }, { opacity: 1, duration: 0.6, delay: 0.3, ease: 'power2.out' });
    }
  }, []);

  const handleNodeClick = useCallback((node: GraphLayoutNode) => {
    if (node.type === 'category') {
      // Click category node → open cluster panel (or close if same)
      if (node.id === selectedClusterId) {
        setSelectedClusterId(null);
      } else {
        setSelectedClusterId(node.id);
      }
    } else if (node.type === 'memory') {
      // Click memory node → close cluster panel, select node
      setSelectedClusterId(null);
      onNodeSelect(node.id === selectedNodeId ? null : node.id);
    } else {
      // Central node → close cluster, reset view
      setSelectedClusterId(null);
      resetView();
    }
  }, [onNodeSelect, selectedNodeId, selectedClusterId, resetView]);

  const handleCloseCluster = useCallback(() => {
    setSelectedClusterId(null);
  }, []);

  const handleUpdateMemory = useCallback((id: string, value: string, importance: number, permanent: boolean) => {
    setMemoryOverrides((prev) => ({ ...prev, [id]: { value, importance, permanent } }));
  }, []);

  // Merge overrides into nodes for ClusterPanel
  const enrichedNodes = React.useMemo(() => {
    return nodes.map((n) => {
      const ov = memoryOverrides[n.id];
      if (ov && n.type === 'memory') {
        return { ...n, value: ov.value, importance: ov.importance, permanent: ov.permanent };
      }
      return n;
    });
  }, [nodes, memoryOverrides]);

  const handleBackgroundClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if ((target.tagName === 'svg' || target.closest('svg') === svgRef.current) && !(target.closest?.('[data-node]'))) {
      setSelectedClusterId(null);
      onNodeSelect(null);
    }
  }, [onNodeSelect]);

  const graphTransform = React.useMemo(() => `translate(${panX}, ${panY}) scale(${zoom})`, [panX, panY, zoom]);

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
          {connections.map((conn) => (
            <ConnectionLine key={conn.id} connection={conn}
              selectedNodeId={selectedNodeId} />
          ))}
          {nodes.map((node) => (
            <GraphNode key={node.id} node={node} isSelected={node.id === selectedNodeId}
              emphasisMode={showEmphasis} selectedNodeId={selectedNodeId} onClick={handleNodeClick} />
          ))}
        </g>
      </svg>
      <GraphHeader totalNodes={visibleMemoryCount} searchQuery={searchQuery} onSearchChange={setSearchQuery}
        showEmphasis={showEmphasis} onToggleEmphasis={setShowEmphasis}
        zoom={zoom} onZoomIn={zoomIn} onZoomOut={zoomOut} onResetView={resetView} />

      {/* Cluster Info Panel */}
      <ClusterPanel
        categoryNode={enrichedNodes.find((n) => n.id === selectedClusterId) ?? null}
        allNodes={enrichedNodes}
        onUpdateMemory={handleUpdateMemory}
        onClose={handleCloseCluster}
      />
    </div>
  );
}
