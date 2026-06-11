import React, { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import type { GraphLayoutNode } from './useGraphLayout';
import { getNodeColor, getNodeGlow } from './useGraphLayout';
import type { CategoryType } from '@/console/types/graph';

function hexagonPoints(cx: number, cy: number, side: number): string {
  const pts: string[] = [];
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 180) * (60 * i - 30);
    const x = cx + side * Math.cos(angle);
    const y = cy + side * Math.sin(angle);
    pts.push(`${x},${y}`);
  }
  return pts.join(' ');
}

const CategoryIcon = ({ category, size = 14 }: { category: CategoryType; size?: number }) => {
  const icons: Record<string, React.ReactNode> = {
    identity: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2a5 5 0 0 1 5 5v2a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5z" />
        <path d="M12 14v8" />
        <path d="M9 18h6" />
      </svg>
    ),
    preferences: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
      </svg>
    ),
    events: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
        <line x1="16" y1="2" x2="16" y2="6" />
        <line x1="8" y1="2" x2="8" y2="6" />
        <line x1="3" y1="10" x2="21" y2="10" />
      </svg>
    ),
    directives: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="4 17 10 11 4 5" />
        <line x1="12" y1="19" x2="20" y2="19" />
      </svg>
    ),
    health: (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    ),
  };

  return <>{icons[category] ?? null}</>;
};

const SelectionRing = React.memo(function SelectionRing({ cx, cy, radius, color }: {
  cx: number; cy: number; radius: number; color: string;
}) {
  return (
    <motion.circle
      cx={cx} cy={cy} r={radius}
      fill="none" stroke={color} strokeWidth={1}
      initial={{ r: radius * 0.3, opacity: 0.6 }}
      animate={{ r: radius * 1.5, opacity: 0 }}
      transition={{ duration: 0.5, ease: [0.4, 0, 0.2, 1] }}
    />
  );
});

const CentralNode = React.memo(function CentralNode({ node, isSelected, onClick }: {
  node: GraphLayoutNode; isSelected: boolean; onClick: (node: GraphLayoutNode) => void;
}) {
  const color = '#22d3ee';
  const hexPoints = hexagonPoints(node.computedX, node.computedY, node.radius);
  const innerHexPoints = hexagonPoints(node.computedX, node.computedY, 16);
  const [isHovered, setIsHovered] = useState(false);

  return (
    <g
      data-node="central"
      onClick={() => onClick(node)}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{ cursor: 'pointer' }}
    >
      <defs>
        <radialGradient id="central-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={color} stopOpacity={0.12} />
          <stop offset="100%" stopColor={color} stopOpacity={0.02} />
        </radialGradient>
        <radialGradient id="central-fill" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={color} stopOpacity={0.12} />
          <stop offset="70%" stopColor={color} stopOpacity={0.04} />
          <stop offset="100%" stopColor={color} stopOpacity={0.02} />
        </radialGradient>
        <filter id="central-drop-shadow">
          <feDropShadow dx="0" dy="0" stdDeviation={isHovered ? 12 : 8} floodColor={color} floodOpacity={isHovered ? 0.25 : 0.15} />
        </filter>
      </defs>

      {isSelected && (
        <SelectionRing cx={node.computedX} cy={node.computedY} radius={node.radius * 1.2} color={color} />
      )}

      <motion.g
        animate={{ scale: isHovered ? 1.08 : 1 }}
        transition={{ duration: 0.25, ease: [0.34, 1.56, 0.64, 1] }}
        style={{ transformOrigin: `${node.computedX}px ${node.computedY}px` }}
      >
        <circle cx={node.computedX} cy={node.computedY} r={node.radius * 1.3}
          fill="url(#central-glow)" opacity={isHovered ? 0.8 : 0.5} />
        <polygon points={hexPoints} fill="url(#central-fill)" stroke={color}
          strokeWidth={isHovered ? 2 : 1.5} strokeOpacity={isHovered ? 1 : 0.8}
          filter="url(#central-drop-shadow)" style={{ transition: 'stroke-width 0.25s ease' }} />
        <polygon points={innerHexPoints} fill={`${color}26`} stroke={color}
          strokeWidth={1} strokeOpacity={0.6} />
      </motion.g>

      <text x={node.computedX} y={node.computedY + node.radius + 18}
        textAnchor="middle" fill="#f8fafc" fontSize={14} fontWeight={700}
        fontFamily="'JetBrains Mono', ui-monospace, monospace"
        style={{ pointerEvents: 'none', textShadow: '0 1px 3px rgba(0,0,0,0.9), 0 0 6px rgba(0,0,0,0.6)' }}>
        {node.label}
      </text>
      <text x={node.computedX} y={node.computedY + node.radius + 32}
        textAnchor="middle" fill="#64748b" fontSize={9} fontWeight={500}
        fontFamily="'JetBrains Mono', ui-monospace, monospace" letterSpacing="0.1em"
        style={{ pointerEvents: 'none', textShadow: '0 1px 2px rgba(0,0,0,0.8)' }}>
        {node.subtitle?.toUpperCase()}
      </text>
    </g>
  );
});

const CategoryNode = React.memo(function CategoryNode({ node, isSelected, onClick }: {
  node: GraphLayoutNode; isSelected: boolean; onClick: (node: GraphLayoutNode) => void;
}) {
  const color = getNodeColor(node);
  const glow = getNodeGlow(node);
  const hexPoints = hexagonPoints(node.computedX, node.computedY, node.radius);
  const [isHovered, setIsHovered] = useState(false);

  const categoryIndex = useMemo(() => {
    const order: CategoryType[] = ['identity', 'preferences', 'events', 'directives', 'health'];
    return order.indexOf(node.category);
  }, [node.category]);

  return (
    <g data-node="category"
      onClick={() => onClick(node)}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{ cursor: 'pointer' }}>
      <defs>
        <radialGradient id={`cat-fill-${node.id}`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={color} stopOpacity={0.1} />
          <stop offset="100%" stopColor={color} stopOpacity={0.04} />
        </radialGradient>
        <filter id={`cat-shadow-${node.id}`}>
          <feDropShadow dx="0" dy="0" stdDeviation={isHovered ? 14 : 8} floodColor={color} floodOpacity={isHovered ? 0.3 : 0.15} />
        </filter>
      </defs>

      {isSelected && (
        <SelectionRing cx={node.computedX} cy={node.computedY} radius={node.radius * 1.3} color={color} />
      )}

      <motion.g
        animate={{ scale: isHovered ? 1.18 : 1 }}
        transition={{ duration: 0.25, ease: [0.34, 1.56, 0.64, 1] }}
        style={{ transformOrigin: `${node.computedX}px ${node.computedY}px` }}>
        <circle cx={node.computedX} cy={node.computedY} r={node.radius * 1.4}
          fill={glow} opacity={isHovered ? 0.9 : 0.6}
          style={{ animation: `glow-pulse 3s ease-in-out infinite`, animationDelay: `${categoryIndex * 0.6}s` }} />
        <polygon points={hexPoints} fill={`url(#cat-fill-${node.id})`} stroke={color}
          strokeWidth={isHovered ? 2 : 1.5} strokeOpacity={isHovered ? 1 : 0.65}
          filter={`url(#cat-shadow-${node.id})`} style={{ transition: 'stroke-width 0.25s ease' }} />
        <foreignObject x={node.computedX - 7} y={node.computedY - 7} width={14} height={14}
          style={{ pointerEvents: 'none' }}>
          <div style={{ color, opacity: 0.8, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <CategoryIcon category={node.category} size={14} />
          </div>
        </foreignObject>
      </motion.g>

      <text x={node.computedX} y={node.computedY + node.radius + 14}
        textAnchor="middle" fill="#f8fafc" fontSize={12} fontWeight={600}
        fontFamily="'Inter', system-ui, sans-serif"
        style={{ pointerEvents: 'none', textShadow: '0 1px 3px rgba(0,0,0,0.9), 0 0 6px rgba(0,0,0,0.6)' }}>
        {node.label}
      </text>
      <text x={node.computedX} y={node.computedY + node.radius + 26}
        textAnchor="middle" fill="#64748b" fontSize={10} fontWeight={500}
        fontFamily="'JetBrains Mono', ui-monospace, monospace"
        style={{ pointerEvents: 'none', textShadow: '0 1px 2px rgba(0,0,0,0.8)' }}>
        {node.subtitle}
      </text>
    </g>
  );
});

const ClusterNode = React.memo(function ClusterNode({ node, isSelected, onClick }: {
  node: GraphLayoutNode; isSelected: boolean; onClick: (node: GraphLayoutNode) => void;
}) {
  const color = getNodeColor(node);
  const glow = getNodeGlow(node);
  const hexPoints = hexagonPoints(node.computedX, node.computedY, node.radius);
  const [isHovered, setIsHovered] = useState(false);
  const count = node.subtitle ?? '';

  return (
    <g data-node="cluster"
      onClick={() => onClick(node)}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{ cursor: 'pointer' }}>
      <defs>
        <filter id={`cluster-shadow-${node.id}`}>
          <feDropShadow dx="0" dy="0" stdDeviation={isHovered ? 12 : 6} floodColor={color} floodOpacity={isHovered ? 0.35 : 0.18} />
        </filter>
      </defs>

      {isSelected && (
        <SelectionRing cx={node.computedX} cy={node.computedY} radius={node.radius * 1.4} color={color} />
      )}

      {/* Expanded state: a slow-spinning orbit ring shows the open subtree. */}
      {node.expanded && (
        <g style={{ transformOrigin: `${node.computedX}px ${node.computedY}px`, animation: 'spin 14s linear infinite' }}>
          <circle cx={node.computedX} cy={node.computedY} r={node.radius * 1.8}
            fill="none" stroke={color} strokeWidth={0.8} strokeOpacity={0.35}
            strokeDasharray="3 7" strokeLinecap="round" />
        </g>
      )}

      <motion.g
        animate={{ scale: isHovered ? 1.18 : 1 }}
        transition={{ duration: 0.25, ease: [0.34, 1.56, 0.64, 1] }}
        style={{ transformOrigin: `${node.computedX}px ${node.computedY}px` }}>
        <circle cx={node.computedX} cy={node.computedY} r={node.radius * 1.7}
          fill={glow} opacity={isHovered || node.expanded ? 0.85 : 0.45} />
        <polygon points={hexPoints}
          fill={node.expanded ? `${color}30` : `${color}14`}
          stroke={color}
          strokeWidth={isHovered ? 1.8 : 1.2}
          strokeOpacity={node.expanded ? 0.95 : 0.6}
          filter={`url(#cluster-shadow-${node.id})`}
          style={{ transition: 'fill 0.3s ease, stroke-opacity 0.3s ease' }} />
        {/* Collapsed: the badge invites the click — "+N inside". */}
        <text x={node.computedX} y={node.computedY + 4}
          textAnchor="middle" fill={color} fontSize={node.expanded ? 10 : 11} fontWeight={700}
          fontFamily="'JetBrains Mono', ui-monospace, monospace"
          style={{ pointerEvents: 'none' }}>
          {node.expanded ? '−' : `+${count}`}
        </text>
      </motion.g>

      <text x={node.computedX} y={node.computedY + node.radius + 15}
        textAnchor="middle" fill="#f8fafc" fontSize={11.5} fontWeight={600}
        fontFamily="'Inter', system-ui, sans-serif"
        style={{ pointerEvents: 'none', textShadow: '0 1px 3px rgba(0,0,0,0.9), 0 0 6px rgba(0,0,0,0.6)' }}>
        {node.label}
      </text>
      {!node.expanded && (
        <text x={node.computedX} y={node.computedY + node.radius + 28}
          textAnchor="middle" fill="#64748b" fontSize={9} fontWeight={500}
          fontFamily="'JetBrains Mono', ui-monospace, monospace" letterSpacing="0.08em"
          style={{ pointerEvents: 'none' }}>
          {count} {Number(count) === 1 ? 'FACT' : 'FACTS'}
        </text>
      )}
    </g>
  );
});

const MemoryLeafNode = React.memo(function MemoryLeafNode({ node, isSelected, emphasisMode, relatedToSelection, unrelatedOpacity, onClick }: {
  node: GraphLayoutNode; isSelected: boolean; emphasisMode: boolean;
  relatedToSelection: boolean; unrelatedOpacity: number;
  onClick: (node: GraphLayoutNode) => void;
}) {
  const color = getNodeColor(node);
  const glow = getNodeGlow(node);
  const [isHovered, setIsHovered] = useState(false);

  let opacity = 1;
  if (emphasisMode) {
    if (node.importance <= 3) opacity = 0.45;
    else if (node.importance <= 6) opacity = 0.75;
    else opacity = 1;
  }
  if (unrelatedOpacity < 1 && !isSelected && !relatedToSelection) {
    opacity = unrelatedOpacity;
  }

  const confidenceAngle = (node.confidence / 100) * 360;
  const confRad = node.radius + 3;
  const confArc = useMemo(() => {
    if (confidenceAngle >= 360) {
      return `M ${node.computedX} ${node.computedY - confRad}
        A ${confRad} ${confRad} 0 1 1 ${node.computedX} ${node.computedY + confRad}
        A ${confRad} ${confRad} 0 1 1 ${node.computedX} ${node.computedY - confRad}`;
    }
    const startAngle = -90;
    const endAngle = startAngle + confidenceAngle;
    const startRad = (startAngle * Math.PI) / 180;
    const endRad = (endAngle * Math.PI) / 180;
    const x1 = node.computedX + confRad * Math.cos(startRad);
    const y1 = node.computedY + confRad * Math.sin(startRad);
    const x2 = node.computedX + confRad * Math.cos(endRad);
    const y2 = node.computedY + confRad * Math.sin(endRad);
    const largeArc = confidenceAngle > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${confRad} ${confRad} 0 ${largeArc} 1 ${x2} ${y2}`;
  }, [node.computedX, node.computedY, confRad, confidenceAngle]);

  return (
    <g data-node="memory" data-node-id={node.id}
      onClick={() => onClick(node)}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{ cursor: 'pointer', opacity, transition: 'opacity 0.4s ease' }}>
      <defs>
        <filter id={`mem-shadow-${node.id}`}>
          <feDropShadow dx="0" dy="0" stdDeviation={isHovered ? 8 : 4} floodColor={color} floodOpacity={isHovered ? 0.35 : 0.15} />
        </filter>
      </defs>

      {isSelected && (
        <SelectionRing cx={node.computedX} cy={node.computedY} radius={node.radius * 1.5} color={color} />
      )}

      <motion.g
        animate={{ scale: isHovered ? 1.25 : (isSelected ? 1.1 : 1) }}
        transition={{ duration: 0.2, ease: [0.34, 1.56, 0.64, 1] }}
        style={{ transformOrigin: `${node.computedX}px ${node.computedY}px` }}>
        <circle cx={node.computedX} cy={node.computedY} r={node.radius * 1.6}
          fill={glow} opacity={isHovered ? 0.9 : 0.5} />
        <path d={confArc} fill="none" stroke={color} strokeWidth={2}
          strokeOpacity={isHovered ? 0.7 : 0.4} strokeLinecap="round" />
        <circle cx={node.computedX} cy={node.computedY} r={node.radius}
          fill={`${color}1F`} stroke={color} strokeWidth={1}
          strokeOpacity={isHovered ? 0.7 : 0.35} filter={`url(#mem-shadow-${node.id})`} />
        <circle cx={node.computedX} cy={node.computedY} r={4}
          fill={color} fillOpacity={isHovered ? 1 : 0.8} />
      </motion.g>

      <text x={node.computedX} y={node.computedY + node.radius + 20}
        textAnchor="middle" fill="#f8fafc" fontSize={11} fontWeight={500}
        fontFamily="'Inter', system-ui, sans-serif"
        style={{ pointerEvents: 'none', textShadow: '0 1px 3px rgba(0,0,0,0.9), 0 0 6px rgba(0,0,0,0.6)', opacity: isHovered ? 1 : 0.85, transition: 'opacity 0.2s ease' }}>
        {node.label.length > 12 ? node.label.slice(0, 11) + '..' : node.label}
      </text>

      {isHovered && node.value && (
        <g>
          <rect x={node.computedX - 80} y={node.computedY - node.radius - 42}
            width={160} height={28} rx={8}
            fill="rgba(15, 23, 42, 0.9)" stroke="rgba(34, 211, 238, 0.15)" strokeWidth={1} />
          <text x={node.computedX} y={node.computedY - node.radius - 24}
            textAnchor="middle" fill="#22d3ee" fontSize={12} fontWeight={500}
            fontFamily="'JetBrains Mono', ui-monospace, monospace" style={{ pointerEvents: 'none' }}>
            {node.value.length > 28 ? node.value.slice(0, 27) + '...' : node.value}
          </text>
        </g>
      )}
    </g>
  );
});

export interface GraphNodeProps {
  node: GraphLayoutNode;
  isSelected: boolean;
  emphasisMode: boolean;
  selectedNodeId?: string | null;
  onClick: (node: GraphLayoutNode) => void;
}

export default function GraphNode({ node, isSelected, emphasisMode, selectedNodeId, onClick }: GraphNodeProps) {
  const relatedToSelection = (() => {
    if (!selectedNodeId) return false;
    if (node.id === selectedNodeId) return true;
    if (node.parentId === selectedNodeId) return true;
    if (node.children?.includes(selectedNodeId)) return true;
    return false;
  })();
  const unrelatedOpacity = selectedNodeId ? 0.35 : 1;

  switch (node.type) {
    case 'central': return <CentralNode node={node} isSelected={isSelected} onClick={onClick} />;
    case 'category': return <CategoryNode node={node} isSelected={isSelected} onClick={onClick} />;
    case 'cluster': return <ClusterNode node={node} isSelected={isSelected} onClick={onClick} />;
    case 'memory': return (
      <MemoryLeafNode node={node} isSelected={isSelected} emphasisMode={emphasisMode}
        relatedToSelection={relatedToSelection} unrelatedOpacity={unrelatedOpacity} onClick={onClick} />
    );
    default: return null;
  }
}

export { CentralNode, CategoryNode, ClusterNode, MemoryLeafNode };
