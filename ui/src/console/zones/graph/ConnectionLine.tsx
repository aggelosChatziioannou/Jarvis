import React, { useRef, useEffect, useState, useMemo } from 'react';
import type { GraphConnection } from './useGraphLayout';
import gsap from 'gsap';

function computeBezierPath(
  x1: number, y1: number, r1: number,
  x2: number, y2: number, r2: number,
  level: number,
): string {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const dist = Math.sqrt(dx * dx + dy * dy);
  if (dist < 1) return `M ${x1} ${y1}`;

  const nx = dx / dist;
  const ny = dy / dist;
  const startX = x1 + nx * r1;
  const startY = y1 + ny * r1;
  const endX = x2 - nx * r2;
  const endY = y2 - ny * r2;
  const curveStrength = dist * 0.35;
  const px = -ny;
  const py = nx;
  const offset = level === 0 ? 0 : (x1 + x2 + y1 + y2) % 2 === 0 ? 1 : -1;
  const cp1x = startX + nx * curveStrength + px * curveStrength * 0.2 * offset;
  const cp1y = startY + ny * curveStrength + py * curveStrength * 0.2 * offset;
  const cp2x = endX - nx * curveStrength + px * curveStrength * 0.2 * offset;
  const cp2y = endY - ny * curveStrength + py * curveStrength * 0.2 * offset;
  return `M ${startX} ${startY} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${endX} ${endY}`;
}

const TravelingDot = React.memo(function TravelingDot({ pathRef, color, size, duration, delay, speedUp }: {
  pathRef: React.RefObject<SVGPathElement | null>;
  color: string; size: number; duration: number; delay: number; speedUp: boolean;
}) {
  const dotRef = useRef<SVGCircleElement>(null);

  useEffect(() => {
    const path = pathRef.current;
    const dot = dotRef.current;
    if (!path || !dot) return;
    const pathLength = path.getTotalLength?.() || 100;
    const dur = speedUp ? duration * 0.5 : duration;
    gsap.set(dot, { opacity: 1 });
    const obj = { distance: 0 };
    const tween = gsap.to(obj, {
      distance: pathLength, duration: dur, delay: delay / 1000,
      ease: 'none', repeat: -1,
      onUpdate: () => {
        try {
          const point = path.getPointAtLength(obj.distance);
          dot.setAttribute('cx', String(point.x));
          dot.setAttribute('cy', String(point.y));
        } catch { /* ignore */ }
      },
    });
    return () => { tween.kill(); };
  }, [pathRef, duration, delay, speedUp]);

  return (
    <circle ref={dotRef} r={size} fill={color} fillOpacity={speedUp ? 0.9 : 0.65}
      style={{ filter: `drop-shadow(0 0 ${speedUp ? 6 : 4}px ${color})` }} />
  );
});

export default function ConnectionLine({ connection, selectedNodeId, onMouseEnter, onMouseLeave }: {
  connection: GraphConnection; selectedNodeId?: string | null;
  emphasisMode?: boolean; onMouseEnter?: (id: string) => void; onMouseLeave?: (id: string) => void;
}) {
  const pathRef = useRef<SVGPathElement>(null);
  const [isHovered, setIsHovered] = useState(false);
  const [pathLength, setPathLength] = useState(0);
  const { source, target, color, level } = connection;

  const d = useMemo(() => computeBezierPath(
    source.computedX, source.computedY, source.radius,
    target.computedX, target.computedY, target.radius, level
  ), [source, target, level]);

  useEffect(() => {
    if (pathRef.current?.getTotalLength) {
      try { setPathLength(pathRef.current.getTotalLength()); }
      catch { setPathLength(200); }
    }
  }, [d]);

  useEffect(() => {
    const path = pathRef.current;
    if (!path || pathLength === 0) return;
    gsap.set(path, { strokeDasharray: pathLength, strokeDashoffset: pathLength });
    const tween = gsap.to(path, { strokeDashoffset: 0, duration: 0.8, delay: connection.entranceDelay / 1000, ease: 'power2.inOut' });
    return () => { tween.kill(); };
  }, [pathLength, connection.entranceDelay]);

  let strokeOpacity = level === 0 ? 0.2 : 0.18;
  let strokeWidth = level === 0 ? 1.5 : 1;
  let dotCount = level === 0 ? 2 : 1;
  let dotSize = level === 0 ? 3 : 2.5;
  let dotDuration = level === 0 ? 3.5 : 4;
  const dotColor = level === 0 ? '#22d3ee' : color;

  if (isHovered) { strokeOpacity = 0.5; strokeWidth = level === 0 ? 2 : 1.5; dotDuration = level === 0 ? 2 : 2.5; }

  const isRelated = selectedNodeId && (connection.sourceId === selectedNodeId || connection.targetId === selectedNodeId);
  const isUnrelated = selectedNodeId && !isRelated;
  if (isRelated) { strokeOpacity = 0.45; strokeWidth = 1.5; }
  if (isUnrelated) { strokeOpacity *= 0.4; }

  return (
    <g onMouseEnter={() => { setIsHovered(true); onMouseEnter?.(connection.id); }}
      onMouseLeave={() => { setIsHovered(false); onMouseLeave?.(connection.id); }}>
      <path ref={pathRef} d={d} fill="none"
        stroke={isHovered ? '#22d3ee' : (level === 0 ? '#475569' : color)}
        strokeWidth={strokeWidth} strokeOpacity={strokeOpacity} strokeLinecap="round"
        style={{ transition: 'stroke-opacity 0.3s ease, stroke-width 0.3s ease' }} />
      {pathLength > 0 && Array.from({ length: dotCount }).map((_, i) => (
        <TravelingDot key={i} pathRef={pathRef} color={dotColor} size={dotSize}
          duration={dotDuration} delay={level === 0 ? i * 1750 : i * 2000 + connection.entranceDelay} speedUp={isHovered} />
      ))}
    </g>
  );
}
