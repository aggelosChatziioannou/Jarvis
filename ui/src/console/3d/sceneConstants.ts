// ============================================================================
// JARVIS SPATIAL DASHBOARD — V15 SHARED CONSTANTS (single source of truth)
// 6 rooms arranged as a 3x3 hub around a central ATRIUM. Every object is a
// live UI element; furniture modules import room rects + the Interactive system.
// Coordinate convention: +x right, +z toward bottom of plan, +y up.
// Character "front" (visor/eyes) faces +z by default; rotate via rotationY.
// ============================================================================

// ---- STRICT COLOR PALETTE (Section 6) ----
export const PALETTE = {
  void: '#0a0e17',
  floorStandard: '#1e293b',
  floorLiving: '#0f172a',
  floorControl: '#0a0e17',
  wallOuter: '#F0F0F0',
  wallInner: '#E8E8E8',
  wallTop: '#475569',
  cyan: '#22d3ee',
  amber: '#fbbf24',
  whiteLight: '#f8fafc',
  slateDark: '#1e293b',
  purple: '#a78bfa', // wellness
  green: '#10b981', // studio
  controlBlue: '#6366f1', // control
  warningRed: '#ef4444',
  successGreen: '#34d399',
  visorBlack: '#000000',
} as const

// ---- HOUSE DIMENSIONS (V15: 44 x 32 hub) ----
export const HALF_W = 22 // x extent
export const HALF_D = 16 // z extent
export const WT = 0.4 // wall thickness
export const OW_H = 1.7 // outer wall height (hybrid cam leans top-down; fade handles tilt)
export const IW_H = 0.9 // inner wall height — waist-height half-walls
export const ENTRANCE_DOOR_H = 1.6

// ---- 3x3 GRID LINES ----
export const GRID_X = [-7.5, 7.5] as const // vertical divider lines
export const GRID_Z = [-5.5, 5.5] as const // horizontal divider lines

export type RoomKey = 'entrance' | 'living' | 'office' | 'wellness' | 'studio' | 'control' | 'atrium'

export interface RoomRect {
  key: RoomKey
  label: string
  x0: number
  x1: number
  z0: number
  z1: number
  floor: string
  tint: string // emissive floor wash colour
  tintIntensity: number
  accent: string // room accent / ambient light colour
  ambientIntensity: number
}

// Room rectangles (footprints). Atrium is the open central cell.
export const ROOMS: Record<RoomKey, RoomRect> = {
  entrance: { key: 'entrance', label: 'ENTRANCE', x0: -HALF_W, x1: -7.5, z0: -HALF_D, z1: -5.5, floor: '#1e293b', tint: '#f8fafc', tintIntensity: 0.05, accent: '#f8fafc', ambientIntensity: 1.3 },
  living: { key: 'living', label: 'LIVING ROOM', x0: -7.5, x1: HALF_W, z0: -HALF_D, z1: -5.5, floor: '#0f172a', tint: '#fbbf24', tintIntensity: 0.05, accent: '#fbbf24', ambientIntensity: 1.7 },
  office: { key: 'office', label: 'OFFICE', x0: -HALF_W, x1: -7.5, z0: -5.5, z1: HALF_D, floor: '#1e293b', tint: '#22d3ee', tintIntensity: 0.06, accent: '#22d3ee', ambientIntensity: 1.55 },
  wellness: { key: 'wellness', label: 'WELLNESS', x0: 7.5, x1: HALF_W, z0: -5.5, z1: 5.5, floor: '#1e293b', tint: '#a78bfa', tintIntensity: 0.06, accent: '#a78bfa', ambientIntensity: 1.5 },
  studio: { key: 'studio', label: 'STUDIO / DEV', x0: -7.5, x1: 7.5, z0: 5.5, z1: HALF_D, floor: '#1e293b', tint: '#10b981', tintIntensity: 0.05, accent: '#10b981', ambientIntensity: 1.45 },
  control: { key: 'control', label: 'CONTROL', x0: 7.5, x1: HALF_W, z0: 5.5, z1: HALF_D, floor: '#0a0e17', tint: '#6366f1', tintIntensity: 0.08, accent: '#6366f1', ambientIntensity: 1.7 },
  atrium: { key: 'atrium', label: 'ATRIUM', x0: -7.5, x1: 7.5, z0: -5.5, z1: 5.5, floor: '#0b0f1a', tint: '#22d3ee', tintIntensity: 0.025, accent: '#22d3ee', ambientIntensity: 0.8 },
}

export const ROOM_LIST: RoomKey[] = ['entrance', 'living', 'office', 'wellness', 'studio', 'control', 'atrium']

// Helper: room centre
export function roomCenter(r: RoomRect): [number, number, number] {
  return [(r.x0 + r.x1) / 2, 0, (r.z0 + r.z1) / 2]
}

// ---- WALL RUNS (axis line + solid extent + archway gaps) ----
export interface WallRun {
  axis: 'x' | 'z' // wall runs ALONG this axis
  fixed: number // the perpendicular coordinate
  from: number
  to: number
  gaps: [number, number][] // open archway intervals along the run axis
  outer?: boolean // taller exterior wall
}

const GAP = 4 // standard archway width (atrium connections)
const DGAP = 3.4 // door/side archway width

export const WALL_RUNS: WallRun[] = [
  // ---- OUTER PERIMETER (taller) ----
  // Top exterior (z=-16) with the entrance door opening (entrance centre x=-14.75)
  { axis: 'x', fixed: -HALF_D, from: -HALF_W, to: HALF_W, gaps: [[-14.75 - 1.6, -14.75 + 1.6]], outer: true },
  // Bottom exterior (z=16)
  { axis: 'x', fixed: HALF_D, from: -HALF_W, to: HALF_W, gaps: [], outer: true },
  // Left exterior (x=-22)
  { axis: 'z', fixed: -HALF_W, from: -HALF_D, to: HALF_D, gaps: [], outer: true },
  // Right exterior (x=22)
  { axis: 'z', fixed: HALF_W, from: -HALF_D, to: HALF_D, gaps: [], outer: true },

  // ---- INNER DIVIDERS (half-height) ----
  // Vertical x=-7.5 (Entrance|Living top, Office|Atrium mid, Office|Studio bottom)
  {
    axis: 'z', fixed: -7.5, from: -HALF_D, to: HALF_D,
    gaps: [
      [-10.75 - GAP / 2, -10.75 + GAP / 2], // Entrance <-> Living
      [-GAP / 2, GAP / 2], // Office <-> Atrium
      [10.75 - DGAP / 2, 10.75 + DGAP / 2], // Office <-> Studio
    ],
  },
  // Vertical x=7.5 — only from z=-5.5..16 (Living spans across x=7.5 in the top row → no wall there)
  {
    axis: 'z', fixed: 7.5, from: -5.5, to: HALF_D,
    gaps: [
      [-GAP / 2, GAP / 2], // Atrium <-> Wellness
      [10.75 - DGAP / 2, 10.75 + DGAP / 2], // Studio <-> Control
    ],
  },
  // Horizontal z=-5.5 (Entrance|Office left, Living|Atrium centre, Living|Wellness right)
  {
    axis: 'x', fixed: -5.5, from: -HALF_W, to: HALF_W,
    gaps: [
      [-14.75 - DGAP / 2, -14.75 + DGAP / 2], // Entrance <-> Office
      [-GAP / 2, GAP / 2], // Living <-> Atrium
      [14.75 - DGAP / 2, 14.75 + DGAP / 2], // Living <-> Wellness
    ],
  },
  // Horizontal z=5.5 — only x=-7.5..22 (Office spans mid+bottom on left → no wall there)
  {
    axis: 'x', fixed: 5.5, from: -7.5, to: HALF_W,
    gaps: [
      [-GAP / 2, GAP / 2], // Atrium <-> Studio
      [14.75 - DGAP / 2, 14.75 + DGAP / 2], // Wellness <-> Control
    ],
  },
]

// Atrium connection floor light-strip endpoints (cyan strips on the floor in each archway)
export const ATRIUM_ARCHWAYS: { pos: [number, number, number]; horizontal: boolean }[] = [
  { pos: [0, 0.03, -5.5], horizontal: true }, // Living
  { pos: [0, 0.03, 5.5], horizontal: true }, // Studio
  { pos: [-7.5, 0.03, 0], horizontal: false }, // Office
  { pos: [7.5, 0.03, 0], horizontal: false }, // Wellness
]

// ---- CAMERA (Hybrid: near top-down default, tiltable to 45°) ----
export const CAMERA = {
  position: [0, 52, 13] as [number, number, number], // ~76° elevation
  fov: 38,
  near: 0.1,
  far: 400,
  target: [0, 0, 0] as [number, number, number],
  minPolarAngle: 0.05,
  maxPolarAngle: Math.PI / 4, // tilt down to 45°
  minDistance: 28,
  maxDistance: 120,
}

// ---- OPERATOR ----
export const AVATAR_HEIGHT = 3.2 // larger — clear focal point in the big 44x32 hub
export const ATRIUM_HOME: [number, number, number] = [0, 0, 0] // idle base (atrium centre)

export type OperatorPose = 'idle' | 'walk' | 'sit' | 'reach' | 'point' | 'cross' | 'lookout' | 'type' | 'press'

// ---- SYSTEM MOOD → glow colour ----
export const MOOD_COLOR = {
  idle: PALETTE.cyan,
  processing: PALETTE.cyan,
  busy: PALETTE.amber,
  warning: PALETTE.warningRed,
  success: PALETTE.successGreen,
} as const

// Idle-wander candidate look points (room entrances around the atrium)
export const WANDER_POINTS: [number, number, number][] = [
  [0, 0, -4.5], // toward Living
  [-4.5, 0, 0], // toward Office
  [4.5, 0, 0], // toward Wellness
  [0, 0, 4.5], // toward Studio
  [0, 0, 0], // home centre
]

// ---- ROOM FOCUS camera (cinematic 3/4 lock per room) ----
const FOCUS_ELEV = (35 * Math.PI) / 180 // ~35° elevation
// Horizontal direction FROM room target TO camera (so camera looks toward the
// room's feature/outer wall and the near wall fades via the cutaway system).
const FOCUS_DIR: Record<RoomKey, [number, number]> = {
  entrance: [0, 1], // look -z toward top door wall
  living: [0, 1], // look -z toward top console/screen wall
  office: [1, 0], // look -x toward left calendar/board wall
  wellness: [-1, 0], // look +x toward right sleep-tracker wall
  studio: [0, -1], // look +z toward bottom code/debug wall
  control: [0, -1], // look +z toward bottom monitor wall
  atrium: [0, 1], // hero on the operator
}

export interface FocusView {
  target: [number, number, number]
  position: [number, number, number]
}

function buildFocus(r: RoomRect, dir: [number, number], pad: number): FocusView {
  const cx = (r.x0 + r.x1) / 2
  const cz = (r.z0 + r.z1) / 2
  const size = Math.max(r.x1 - r.x0, r.z1 - r.z0)
  const dist = size * 0.9 + pad
  const horiz = dist * Math.cos(FOCUS_ELEV)
  const vert = dist * Math.sin(FOCUS_ELEV)
  const ty = 0.9
  return {
    target: [cx, ty, cz],
    position: [cx + dir[0] * horiz, ty + vert, cz + dir[1] * horiz],
  }
}

export const FOCUS_CONFIG: Record<RoomKey, FocusView> = {
  entrance: buildFocus(ROOMS.entrance, FOCUS_DIR.entrance, 9),
  living: buildFocus(ROOMS.living, FOCUS_DIR.living, 8),
  office: buildFocus(ROOMS.office, FOCUS_DIR.office, 8),
  wellness: buildFocus(ROOMS.wellness, FOCUS_DIR.wellness, 9),
  studio: buildFocus(ROOMS.studio, FOCUS_DIR.studio, 9),
  control: buildFocus(ROOMS.control, FOCUS_DIR.control, 9),
  atrium: buildFocus(ROOMS.atrium, FOCUS_DIR.atrium, 4),
}

// Focus mode lets the camera tilt lower than the hub clamp.
export const FOCUS_MAX_POLAR = 1.18 // ~68° from vertical

// Which room contains a world point (atrium fallback).
export function roomKeyAt(p: [number, number, number]): RoomKey {
  for (const k of ['entrance', 'living', 'office', 'wellness', 'studio', 'control'] as RoomKey[]) {
    const r = ROOMS[k]
    if (p[0] >= r.x0 && p[0] <= r.x1 && p[2] >= r.z0 && p[2] <= r.z1) return k
  }
  return 'atrium'
}

// ---- ROOM CONNECTIVITY GRAPH (archway doors) — for walk pathfinding ----
// Each edge's `door` is the [x,z] centre of the archway gap between two rooms.
// A straight line between two doors of the SAME (convex) room never crosses a
// wall, so a path that hops door->door->anchor keeps the Operator off the walls.
interface RoomEdge { to: RoomKey; door: [number, number] }
const ROOM_ADJ: Record<RoomKey, RoomEdge[]> = {
  atrium: [
    { to: 'living', door: [0, -5.5] },
    { to: 'office', door: [-7.5, 0] },
    { to: 'wellness', door: [7.5, 0] },
    { to: 'studio', door: [0, 5.5] },
  ],
  living: [
    { to: 'atrium', door: [0, -5.5] },
    { to: 'entrance', door: [-7.5, -10.75] },
    { to: 'wellness', door: [14.75, -5.5] },
  ],
  office: [
    { to: 'atrium', door: [-7.5, 0] },
    { to: 'entrance', door: [-14.75, -5.5] },
    { to: 'studio', door: [-7.5, 10.75] },
  ],
  wellness: [
    { to: 'atrium', door: [7.5, 0] },
    { to: 'living', door: [14.75, -5.5] },
    { to: 'control', door: [14.75, 5.5] },
  ],
  studio: [
    { to: 'atrium', door: [0, 5.5] },
    { to: 'office', door: [-7.5, 10.75] },
    { to: 'control', door: [7.5, 10.75] },
  ],
  control: [
    { to: 'wellness', door: [14.75, 5.5] },
    { to: 'studio', door: [7.5, 10.75] },
  ],
  entrance: [
    { to: 'living', door: [-7.5, -10.75] },
    { to: 'office', door: [-14.75, -5.5] },
  ],
}

// Shortest sequence of door waypoints to walk from `from` room to `to` room.
export function findRoomPath(from: RoomKey, to: RoomKey): [number, number, number][] {
  if (from === to) return []
  const prev = new Map<RoomKey, { room: RoomKey; door: [number, number] } | null>()
  prev.set(from, null)
  const queue: RoomKey[] = [from]
  let found = false
  while (queue.length) {
    const cur = queue.shift() as RoomKey
    if (cur === to) { found = true; break }
    for (const e of ROOM_ADJ[cur]) {
      if (!prev.has(e.to)) {
        prev.set(e.to, { room: cur, door: e.door })
        queue.push(e.to)
      }
    }
  }
  if (!found && !prev.has(to)) return []
  const doors: [number, number][] = []
  let r: RoomKey = to
  for (;;) {
    const p = prev.get(r)
    if (!p) break
    doors.push(p.door)
    r = p.room
  }
  doors.reverse()
  return doors.map(([x, z]) => [x, 0, z] as [number, number, number])
}

// Operator walk speed (world units / second) — calm, deliberate.
export const OPERATOR_SPEED = 4.2
