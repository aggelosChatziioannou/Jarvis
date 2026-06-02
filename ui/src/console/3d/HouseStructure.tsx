import { useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import {
  PALETTE,
  HALF_W,
  HALF_D,
  WT,
  OW_H,
  IW_H,
  ROOMS,
  ROOM_LIST,
  WALL_RUNS,
  ATRIUM_ARCHWAYS,
} from './sceneConstants'
import type { RoomRect } from './sceneConstants'

// ---- segment math: [from,to] minus gap intervals -> solid segments ----
function solidSegments(from: number, to: number, gaps: [number, number][]): [number, number][] {
  const sorted = [...gaps].sort((a, b) => a[0] - b[0])
  const segs: [number, number][] = []
  let cur = from
  for (const [a, b] of sorted) {
    if (a > cur) segs.push([cur, Math.min(a, to)])
    cur = Math.max(cur, b)
  }
  if (cur < to) segs.push([cur, to])
  return segs.filter(([a, b]) => b - a > 0.02)
}

// ---- Floor: navy plane + cyan grid + soft per-room emissive wash ----
function Floor({ rect }: { rect: RoomRect }) {
  const w = rect.x1 - rect.x0
  const d = rect.z1 - rect.z0
  const cx = (rect.x0 + rect.x1) / 2
  const cz = (rect.z0 + rect.z1) / 2
  const texture = useMemo(() => {
    const canvas = document.createElement('canvas')
    canvas.width = 256
    canvas.height = 256
    const ctx = canvas.getContext('2d')!
    ctx.fillStyle = rect.floor
    ctx.fillRect(0, 0, 256, 256)
    ctx.strokeStyle = 'rgba(34, 211, 238, 0.07)'
    ctx.lineWidth = 1
    ctx.beginPath()
    for (let i = 0; i <= 256; i += 32) {
      ctx.moveTo(i, 0); ctx.lineTo(i, 256)
      ctx.moveTo(0, i); ctx.lineTo(256, i)
    }
    ctx.stroke()
    const tex = new THREE.CanvasTexture(canvas)
    tex.wrapS = THREE.RepeatWrapping
    tex.wrapT = THREE.RepeatWrapping
    tex.repeat.set(w / 1.6, d / 1.6)
    return tex
  }, [rect.floor, w, d])

  return (
    <mesh position={[cx, 0.02, cz]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
      <planeGeometry args={[w, d]} />
      <meshStandardMaterial map={texture} color={rect.floor} emissive={rect.tint} emissiveIntensity={rect.tintIntensity} roughness={0.85} metalness={0} />
    </mesh>
  )
}

// ---- Inner half-walls (generated from WALL_RUNS, no fade) ----
function InnerWalls() {
  const segs: { pos: [number, number, number]; size: [number, number, number] }[] = []
  for (const run of WALL_RUNS) {
    if (run.outer) continue
    const H = IW_H
    for (const [a, b] of solidSegments(run.from, run.to, run.gaps)) {
      const mid = (a + b) / 2
      if (run.axis === 'x') segs.push({ pos: [mid, H / 2, run.fixed], size: [b - a, H, WT] })
      else segs.push({ pos: [run.fixed, H / 2, mid], size: [WT, H, b - a] })
    }
  }
  return (
    <group>
      {segs.map((s, i) => (
        <mesh key={i} position={s.pos} castShadow receiveShadow>
          <boxGeometry args={s.size} />
          <meshStandardMaterial color={PALETTE.wallInner} roughness={0.7} metalness={0} />
        </mesh>
      ))}
    </group>
  )
}

// ---- Outer perimeter with camera-aware cutaway fade ----
function FadeOuterWalls() {
  const { camera } = useThree()
  const northL = useRef<THREE.MeshStandardMaterial>(null)
  const northR = useRef<THREE.MeshStandardMaterial>(null)
  const south = useRef<THREE.MeshStandardMaterial>(null)
  const west = useRef<THREE.MeshStandardMaterial>(null)
  const east = useRef<THREE.MeshStandardMaterial>(null)

  // door gap on the north (top) wall, in the entrance cell
  const doorC = -14.75
  const northSegs = solidSegments(-HALF_W, HALF_W, [[doorC - 1.6, doorC + 1.6]])

  useFrame(() => {
    const T = 4.5
    const apply = (m: THREE.MeshStandardMaterial | null, near: boolean) => {
      if (!m) return
      const tgt = near ? 0.08 : 1
      m.opacity += (tgt - m.opacity) * 0.12
      m.depthWrite = m.opacity > 0.92
    }
    apply(northL.current, camera.position.z < -T)
    apply(northR.current, camera.position.z < -T)
    apply(south.current, camera.position.z > T)
    apply(west.current, camera.position.x < -T)
    apply(east.current, camera.position.x > T)
  })

  return (
    <group>
      {/* North (split around door) */}
      {northSegs.map(([a, b], i) => (
        <mesh key={`n${i}`} position={[(a + b) / 2, OW_H / 2, -HALF_D]} castShadow receiveShadow>
          <boxGeometry args={[b - a, OW_H, WT]} />
          <meshStandardMaterial ref={i === 0 ? northL : northR} color={PALETTE.wallOuter} roughness={0.7} metalness={0} transparent />
        </mesh>
      ))}
      {/* South */}
      <mesh position={[0, OW_H / 2, HALF_D]} castShadow receiveShadow>
        <boxGeometry args={[HALF_W * 2, OW_H, WT]} />
        <meshStandardMaterial ref={south} color={PALETTE.wallOuter} roughness={0.7} metalness={0} transparent />
      </mesh>
      {/* West */}
      <mesh position={[-HALF_W, OW_H / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[WT, OW_H, HALF_D * 2]} />
        <meshStandardMaterial ref={west} color={PALETTE.wallOuter} roughness={0.7} metalness={0} transparent />
      </mesh>
      {/* East */}
      <mesh position={[HALF_W, OW_H / 2, 0]} castShadow receiveShadow>
        <boxGeometry args={[WT, OW_H, HALF_D * 2]} />
        <meshStandardMaterial ref={east} color={PALETTE.wallOuter} roughness={0.7} metalness={0} transparent />
      </mesh>
    </group>
  )
}

export default function HouseStructure() {
  return (
    <group>
      {/* ===== FLOORS (per room incl. atrium) ===== */}
      {ROOM_LIST.map((k) => (
        <Floor key={k} rect={ROOMS[k]} />
      ))}

      {/* ===== CENTRAL ATRIUM "home base" ring ===== */}
      <mesh position={[0, 0.04, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[1.5, 1.62, 64]} />
        <meshBasicMaterial color={PALETTE.cyan} transparent opacity={0.5} toneMapped={false} depthWrite={false} />
      </mesh>
      <mesh position={[0, 0.035, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[2.4, 2.46, 64]} />
        <meshBasicMaterial color={PALETTE.cyan} transparent opacity={0.22} toneMapped={false} depthWrite={false} />
      </mesh>

      {/* ===== ARCHWAY FLOOR LIGHT STRIPS (atrium connections) ===== */}
      {ATRIUM_ARCHWAYS.map((a, i) => (
        <mesh key={`arch${i}`} position={a.pos} rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={a.horizontal ? [4, 0.5] : [0.5, 4]} />
          <meshBasicMaterial color={PALETTE.cyan} transparent opacity={0.4} toneMapped={false} depthWrite={false} />
        </mesh>
      ))}

      {/* ===== NEON UNDERGLOW (outer base) ===== */}
      {[
        { pos: [0, 0.06, -HALF_D] as [number, number, number], size: [HALF_W * 2, 0.1, 0.18] as [number, number, number] },
        { pos: [0, 0.06, HALF_D] as [number, number, number], size: [HALF_W * 2, 0.1, 0.18] as [number, number, number] },
        { pos: [-HALF_W, 0.06, 0] as [number, number, number], size: [0.18, 0.1, HALF_D * 2] as [number, number, number] },
        { pos: [HALF_W, 0.06, 0] as [number, number, number], size: [0.18, 0.1, HALF_D * 2] as [number, number, number] },
      ].map((s, i) => (
        <mesh key={`ug${i}`} position={s.pos}>
          <boxGeometry args={s.size} />
          <meshStandardMaterial color={PALETTE.cyan} emissive={PALETTE.cyan} emissiveIntensity={2.6} toneMapped={false} />
        </mesh>
      ))}

      <InnerWalls />
      <FadeOuterWalls />
    </group>
  )
}
