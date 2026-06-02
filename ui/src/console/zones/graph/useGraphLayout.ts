import { useMemo } from 'react';
import type { MemoryNode } from '@/console/types/graph';
import { memoryNodes, categories } from '@/console/data/graphMock';

export interface GraphLayoutNode extends MemoryNode {
  computedX: number;
  computedY: number;
  radius: number;
  visible: boolean;
  entranceDelay: number;
}

export interface GraphConnection {
  id: string;
  sourceId: string;
  targetId: string;
  source: GraphLayoutNode;
  target: GraphLayoutNode;
  visible: boolean;
  color: string;
  level: number;
  entranceDelay: number;
}

const CATEGORY_ANGLES: Record<string, number> = {
  identity: -Math.PI / 2,
  preferences: -Math.PI / 2 + (2 * Math.PI) / 5,
  events: -Math.PI / 2 + 2 * (2 * Math.PI) / 5,
  directives: -Math.PI / 2 + 3 * (2 * Math.PI) / 5,
  health: -Math.PI / 2 + 4 * (2 * Math.PI) / 5,
};

const CATEGORY_RADIUS = 185;
const MEMORY_MIN_RADIUS = 120;
const MEMORY_MAX_RADIUS = 175;

function seededRandom(seed: string): () => number {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0;
  }
  return () => {
    hash = (hash * 16807 + 0) % 2147483647;
    return (hash - 1) / 2147483646;
  };
}

function getMemoryRadius(node: MemoryNode): number {
  const imp = node.importance;
  if (imp <= 3) return 10;
  if (imp <= 6) return 13;
  return 16;
}

function getNodeGlow(node: GraphLayoutNode): string {
  const cat = categories.find((c) => c.type === node.category);
  return cat?.glow ?? 'rgba(34, 211, 238, 0.12)';
}

function getNodeColor(node: GraphLayoutNode): string {
  const cat = categories.find((c) => c.type === node.category);
  return cat?.color ?? '#22d3ee';
}

export interface LayoutOptions {
  searchQuery?: string;
  visibleCategories?: Set<string>;
  showEmphasis?: boolean;
}

export function useGraphLayout(options: LayoutOptions = {}) {
  const {
    searchQuery = '',
    visibleCategories = new Set(categories.map((c) => c.type)),
    showEmphasis = false,
  } = options;
  const searchLower = searchQuery.toLowerCase().trim();

  return useMemo(() => {
    const nodeMap = new Map<string, GraphLayoutNode>();
    const connections: GraphConnection[] = [];

    const centralNode = memoryNodes.find((n) => n.type === 'central');
    if (!centralNode) return { nodes: [], connections: [] };

    const centralLayout: GraphLayoutNode = {
      ...centralNode,
      computedX: 0,
      computedY: 0,
      radius: 48,
      visible: true,
      entranceDelay: 500,
    };
    nodeMap.set(centralLayout.id, centralLayout);

    const categoryNodes = memoryNodes.filter((n) => n.type === 'category');
    categoryNodes.forEach((cat, i) => {
      const angle = CATEGORY_ANGLES[cat.category] ?? 0;
      const x = Math.cos(angle) * CATEGORY_RADIUS;
      const y = Math.sin(angle) * CATEGORY_RADIUS;

      const layoutNode: GraphLayoutNode = {
        ...cat,
        computedX: x,
        computedY: y,
        radius: 28,
        visible: visibleCategories.has(cat.category),
        entranceDelay: 700 + i * 100,
      };
      nodeMap.set(layoutNode.id, layoutNode);

      connections.push({
        id: `conn-${centralLayout.id}-${layoutNode.id}`,
        sourceId: centralLayout.id,
        targetId: layoutNode.id,
        source: centralLayout,
        target: layoutNode,
        visible: visibleCategories.has(cat.category),
        color: '#22d3ee',
        level: 0,
        entranceDelay: 1000 + i * 50,
      });
    });

    const memoryLeafs = memoryNodes.filter((n) => n.type === 'memory');
    const memoriesPerCategory = new Map<string, MemoryNode[]>();
    memoryLeafs.forEach((mem) => {
      const list = memoriesPerCategory.get(mem.category) ?? [];
      list.push(mem);
      memoriesPerCategory.set(mem.category, list);
    });

    memoriesPerCategory.forEach((memories, catType) => {
      const parentNode = nodeMap.get(`cat-${catType}`);
      if (!parentNode) return;

      const rand = seededRandom(catType);
      const count = memories.length;
      const angleSpan = (2.5 * Math.PI) / 3;
      const baseAngle = CATEGORY_ANGLES[catType] ?? 0;

      memories.forEach((mem, i) => {
        const frac = count <= 1 ? 0.5 : i / (count - 1);
        const jitterAngle = (rand() - 0.5) * angleSpan * 0.12;
        const angle = baseAngle + (frac - 0.5) * angleSpan + jitterAngle;

        const distJitter = rand() * 16 - 8;
        const distance =
          MEMORY_MIN_RADIUS +
          (MEMORY_MAX_RADIUS - MEMORY_MIN_RADIUS) * (0.3 + rand() * 0.7) +
          distJitter;

        const mx = parentNode.computedX + Math.cos(angle) * distance;
        const my = parentNode.computedY + Math.sin(angle) * distance;

        const matchesSearch =
          !searchLower ||
          mem.label.toLowerCase().includes(searchLower) ||
          (mem.value?.toLowerCase().includes(searchLower) ?? false);

        const categoryVisible = visibleCategories.has(mem.category);
        const visible = categoryVisible && matchesSearch;

        let radius = getMemoryRadius(mem);
        if (showEmphasis) {
          if (mem.importance <= 3) radius *= 0.85;
          else if (mem.importance >= 7) radius *= 1.2;
        }

        const layoutNode: GraphLayoutNode = {
          ...mem,
          computedX: mx,
          computedY: my,
          radius,
          visible,
          entranceDelay: 1200 + connections.length * 30,
        };
        nodeMap.set(layoutNode.id, layoutNode);

        connections.push({
          id: `conn-${parentNode.id}-${layoutNode.id}`,
          sourceId: parentNode.id,
          targetId: layoutNode.id,
          source: parentNode,
          target: layoutNode,
          visible: categoryVisible && matchesSearch,
          color: getNodeColor(layoutNode),
          level: 1,
          entranceDelay: 1000 + connections.length * 50,
        });
      });
    });

    const nodes = Array.from(nodeMap.values());
    return { nodes, connections };
  }, [searchLower, visibleCategories, showEmphasis]);
}

export { getNodeColor, getNodeGlow };
