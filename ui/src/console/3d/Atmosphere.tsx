import { Sparkles, Billboard, Html } from '@react-three/drei'
import { HALF_W, HALF_D, OW_H, ROOMS, ROOM_LIST } from './sceneConstants'

/** Slow-drifting dust motes in the void, like dust in a projector beam. */
export function DustMotes() {
  return (
    <Sparkles
      count={40}
      scale={[HALF_W * 2 + 6, 12, HALF_D * 2 + 6]}
      size={2}
      speed={0.22}
      color="#22d3ee"
      opacity={0.4}
      position={[0, 5, 0]}
    />
  )
}

/**
 * Cheap static "floating on dark water" pad under the house — a dark glossy
 * slab + a soft cyan projector glow. (Replaced the per-frame MeshReflectorMaterial
 * which re-rendered the whole scene every frame and caused camera-rotate lag.)
 */
export function FloorReflection() {
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.05, 0]}>
        <planeGeometry args={[HALF_W * 2 + 26, HALF_D * 2 + 26]} />
        <meshStandardMaterial color="#0c1322" roughness={0.35} metalness={0.6} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]}>
        <circleGeometry args={[Math.max(HALF_W, HALF_D) * 0.95, 64]} />
        <meshBasicMaterial color="#0e2a33" transparent opacity={0.35} depthWrite={false} />
      </mesh>
    </group>
  )
}

/** Glassmorphism floating labels above each room, always facing camera. */
export function FloatingRoomLabels() {
  return (
    <>
      {ROOM_LIST.filter((k) => k !== 'atrium').map((k) => {
        const r = ROOMS[k]
        const cx = (r.x0 + r.x1) / 2
        const cz = (r.z0 + r.z1) / 2
        return (
          <Billboard key={k} position={[cx, OW_H + 1.3, cz]}>
            <Html center distanceFactor={30} zIndexRange={[30, 0]}>
              <div
                style={{
                  padding: '3px 11px',
                  background: 'rgba(10,14,23,0.78)',
                  backdropFilter: 'blur(8px)',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 8,
                  color: r.accent,
                  fontSize: 11,
                  fontWeight: 500,
                  letterSpacing: '1.5px',
                  fontFamily: 'JetBrains Mono, monospace',
                  whiteSpace: 'nowrap',
                  textTransform: 'uppercase',
                  pointerEvents: 'none',
                }}
              >
                {r.label}
              </div>
            </Html>
          </Billboard>
        )
      })}
    </>
  )
}
