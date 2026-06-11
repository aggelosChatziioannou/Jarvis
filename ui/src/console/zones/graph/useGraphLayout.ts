import { useMemo } from 'react';
import type { MemoryNode } from '@/console/types/graph';
import { memoryNodes, categories } from '@/console/data/graphMock';

export interface GraphLayoutNode extends MemoryNode {
  computedX: number;
  computedY: number;
  radius: number;
  visible: boolean;
  entranceDelay: number;
  /** Angle (rad) from this node's parent — children fan outward from it. */
  outwardAngle: number;
  expanded: boolean;
  childTotal: number;
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

const HUB_RADIUS = 195;       // central -> branch hubs
const CLUSTER_RADIUS = 150;   // hub -> themed clusters / direct facts
const LEAF_RADIUS = 105;      // cluster -> fact leaves

function getNodeGlow(node: GraphLayoutNode): string {
  const cat = categories.find((c) => c.type === node.category);
  return cat?.glow ?? 'rgba(34, 211, 238, 0.12)';
}

function getNodeColor(node: GraphLayoutNode): string {
  const cat = categories.find((c) => c.type === node.category);
  return cat?.color ?? '#22d3ee';
}

/** Fan `count` children around `baseAngle`. Wide fans for big families. */
function fanAngles(baseAngle: number, count: number): number[] {
  if (count <= 0) return [];
  if (count === 1) return [baseAngle];
  const span = Math.min(Math.PI * 1.5, Math.max(Math.PI * 0.55, count * 0.42));
  return Array.from({ length: count }, (_, i) =>
    baseAngle + (i / (count - 1) - 0.5) * span);
}

function matchesSearch(n: MemoryNode, q: string): boolean {
  if (!q) return true;
  return n.label.toLowerCase().includes(q) || (n.value?.toLowerCase().includes(q) ?? false);
}

export interface LayoutOptions {
  searchQuery?: string;
  visibleCategories?: Set<string>;
  showEmphasis?: boolean;
  /** Real (mapped) graph nodes; defaults to the demo mock when omitted. */
  nodes?: MemoryNode[];
  /** Ids of hubs/clusters whose children are shown. */
  expandedIds?: Set<string>;
}

export function useGraphLayout(options: LayoutOptions = {}) {
  const {
    searchQuery = '',
    visibleCategories = new Set(categories.map((c) => c.type)),
    showEmphasis = false,
    nodes: inputNodes = memoryNodes,
    expandedIds = new Set<string>(),
  } = options;
  const searchLower = searchQuery.toLowerCase().trim();

  return useMemo(() => {
    const nodeMap = new Map<string, GraphLayoutNode>();
    const connections: GraphConnection[] = [];

    const centralNode = inputNodes.find((n) => n.type === 'central');
    if (!centralNode) return { nodes: [], connections: [] };

    const byParent = new Map<string, MemoryNode[]>();
    for (const n of inputNodes) {
      if (n.type === 'central' || !n.parentId) continue;
      const list = byParent.get(n.parentId) ?? [];
      list.push(n);
      byParent.set(n.parentId, list);
    }

    // Search reveals matches even inside collapsed subtrees: every ancestor
    // of a matching node is force-expanded for the duration of the search.
    const forceExpanded = new Set<string>();
    if (searchLower) {
      const parentOf = new Map(inputNodes.map((n) => [n.id, n.parentId] as const));
      for (const n of inputNodes) {
        if (n.type !== 'memory' || !matchesSearch(n, searchLower)) continue;
        let p = n.parentId;
        while (p) {
          forceExpanded.add(p);
          p = parentOf.get(p) ?? undefined;
        }
      }
    }
    const isExpanded = (id: string) => expandedIds.has(id) || forceExpanded.has(id);

    const centralLayout: GraphLayoutNode = {
      ...centralNode,
      computedX: 0, computedY: 0, radius: 48,
      visible: true, entranceDelay: 400,
      outwardAngle: 0, expanded: true,
      childTotal: byParent.get(centralNode.id)?.length ?? 0,
    };
    nodeMap.set(centralLayout.id, centralLayout);

    function place(
      parent: GraphLayoutNode,
      children: MemoryNode[],
      ringRadius: number,
      level: number,
      parentVisible: boolean,
    ) {
      const angles = parent.type === 'central'
        ? children.map((c) => CATEGORY_ANGLES[c.category] ?? 0)
        : fanAngles(parent.outwardAngle, children.length);

      children.forEach((child, i) => {
        const angle = angles[i];
        const x = parent.computedX + Math.cos(angle) * ringRadius;
        const y = parent.computedY + Math.sin(angle) * ringRadius;
        const kids = byParent.get(child.id) ?? [];
        const expanded = isExpanded(child.id);

        const searchVisible = child.type !== 'memory' || matchesSearch(child, searchLower);
        const visible = parentVisible && visibleCategories.has(child.category) && searchVisible;

        let radius = child.type === 'category' ? 30 : child.type === 'cluster' ? 20 : 11;
        if (showEmphasis && child.type === 'memory') {
          if (child.importance <= 3) radius *= 0.85;
          else if (child.importance >= 7) radius *= 1.2;
        }

        const layoutNode: GraphLayoutNode = {
          ...child,
          computedX: x, computedY: y, radius,
          visible,
          entranceDelay: 120 + level * 160 + i * 55,
          outwardAngle: angle,
          expanded,
          childTotal: kids.length,
        };
        nodeMap.set(layoutNode.id, layoutNode);

        connections.push({
          id: `conn-${parent.id}-${layoutNode.id}`,
          sourceId: parent.id,
          targetId: layoutNode.id,
          source: parent,
          target: layoutNode,
          visible,
          color: getNodeColor(layoutNode),
          level,
          entranceDelay: 80 + level * 160 + i * 45,
        });

        if (kids.length) {
          place(layoutNode, kids, level === 0 ? CLUSTER_RADIUS : LEAF_RADIUS, level + 1, visible && expanded);
        }
      });
    }

    place(centralLayout, byParent.get(centralLayout.id) ?? [], HUB_RADIUS, 0, true);

    const nodes = Array.from(nodeMap.values());
    return { nodes, connections };
  }, [searchLower, visibleCategories, showEmphasis, inputNodes, expandedIds]);
}

export { getNodeColor, getNodeGlow };
