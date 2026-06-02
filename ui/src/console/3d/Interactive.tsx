import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import type { Interaction, NotifSpark } from './dollhouseTypes'
import type { OperatorPose } from './sceneConstants'

// ---------------------------------------------------------------------------
// <Interactive> — wraps any object to make it a live UI element:
//   hover  -> lifts 0.12, shows a cyan base ring + glass tooltip, head-tracks avatar
//   click  -> ripple ring + Operator walks to `anchor` & plays its pose
//   active -> persistent base ring while it is the current target
// Objects render in WORLD coordinates. `position` = object centre (tooltip / ring
// origin); `anchor` = where the Operator stands to use it.
// ---------------------------------------------------------------------------
export interface InteractiveProps {
  id: string
  label: string
  status?: string
  position: [number, number, number]
  anchor: { position: [number, number, number]; rotationY: number; pose: OperatorPose }
  ix: Interaction
  accent?: string
  ringRadius?: number
  tooltipHeight?: number
  children: ReactNode
}

export function Interactive({
  id,
  label,
  status,
  position,
  anchor,
  ix,
  accent = '#22d3ee',
  ringRadius = 1.1,
  tooltipHeight = 1.7,
  children,
}: InteractiveProps) {
  const lift = useRef<THREE.Group>(null)
  const ringMat = useRef<THREE.MeshBasicMaterial>(null)
  const ripple = useRef<THREE.Mesh>(null)
  const rippleMat = useRef<THREE.MeshBasicMaterial>(null)
  const rippleT = useRef(-1) // -1 = idle, else 0..1 progress
  const [hovered, setHovered] = useState(false)
  const active = ix.activeId === id

  useFrame((_, delta) => {
    // hover lift
    if (lift.current) {
      const targetY = hovered ? 0.12 : 0
      lift.current.position.y += (targetY - lift.current.position.y) * Math.min(1, delta * 10)
    }
    // base ring opacity (hover or active)
    if (ringMat.current) {
      const targetO = hovered ? 0.85 : active ? 0.5 : 0
      ringMat.current.opacity += (targetO - ringMat.current.opacity) * Math.min(1, delta * 8)
    }
    // click ripple
    if (rippleT.current >= 0 && ripple.current && rippleMat.current) {
      rippleT.current += delta * 1.8
      const t = rippleT.current
      const s = 0.4 + t * 2.2
      ripple.current.scale.set(s, s, s)
      rippleMat.current.opacity = Math.max(0, 0.8 * (1 - t))
      if (t >= 1) {
        rippleT.current = -1
        ripple.current.visible = false
      }
    }
  })

  const onOver = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation()
    setHovered(true)
    document.body.style.cursor = 'pointer'
    ix.hover({ id, label, position })
  }
  const onOut = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation()
    setHovered(false)
    document.body.style.cursor = 'auto'
    ix.hover(null)
  }
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    // fire ripple
    if (ripple.current) {
      ripple.current.visible = true
      rippleT.current = 0
    }
    ix.activate({ id, position: anchor.position, rotationY: anchor.rotationY, pose: anchor.pose })
    ix.notify(position, accent)
  }

  return (
    <group>
      {/* interactive children that lift on hover */}
      <group ref={lift} onPointerOver={onOver} onPointerOut={onOut} onClick={onClick}>
        {children}
      </group>

      {/* base hover/active ring */}
      <mesh position={[position[0], 0.045, position[2]]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[ringRadius, ringRadius + 0.12, 48]} />
        <meshBasicMaterial ref={ringMat} color={accent} transparent opacity={0} depthWrite={false} toneMapped={false} />
      </mesh>

      {/* click ripple */}
      <mesh ref={ripple} visible={false} position={[position[0], 0.05, position[2]]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[ringRadius * 0.7, ringRadius * 0.85, 48]} />
        <meshBasicMaterial ref={rippleMat} color={accent} transparent opacity={0} depthWrite={false} toneMapped={false} />
      </mesh>

      {/* tooltip on hover */}
      {hovered && (
        <Html position={[position[0], position[1] + tooltipHeight, position[2]]} center distanceFactor={26} zIndexRange={[40, 0]}>
          <div
            style={{
              padding: '5px 11px',
              background: 'rgba(10,14,23,0.88)',
              backdropFilter: 'blur(8px)',
              border: `1px solid ${accent}55`,
              borderRadius: 8,
              whiteSpace: 'nowrap',
              fontFamily: 'JetBrains Mono, monospace',
              boxShadow: `0 0 14px ${accent}33`,
              pointerEvents: 'none',
              transform: 'translateY(-4px)',
            }}
          >
            <div style={{ color: accent, fontSize: 11, fontWeight: 600, letterSpacing: '0.5px' }}>{label}</div>
            {status && <div style={{ color: '#94a3b8', fontSize: 9, marginTop: 1 }}>{status}</div>}
          </div>
        </Html>
      )}
    </group>
  )
}

// ---------------------------------------------------------------------------
// NotificationOrbs — glowing orbs that fly from a source to the Operator, then pop.
// operatorPos is a live Vector3 ref updated by the Operator each frame.
// ---------------------------------------------------------------------------
function Orb({
  spark,
  operatorPos,
  onDone,
}: {
  spark: NotifSpark
  operatorPos: React.RefObject<THREE.Vector3>
  onDone: (id: number) => void
}) {
  const ref = useRef<THREE.Mesh>(null)
  const t = useRef(0)
  const from = new THREE.Vector3(spark.from[0], spark.from[1], spark.from[2])
  const tmp = useRef(new THREE.Vector3())

  useFrame((_, delta) => {
    const m = ref.current
    if (!m) return
    t.current += delta / 1.1 // ~1.1s flight
    const k = Math.min(1, t.current)
    const dest = operatorPos.current ?? new THREE.Vector3(0, 1.2, 0)
    // ease-in-out
    const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2
    tmp.current.lerpVectors(from, dest, e)
    // arc upward in the middle
    const arc = Math.sin(k * Math.PI) * 1.6
    m.position.set(tmp.current.x, tmp.current.y + arc + 0.4, tmp.current.z)
    const pop = k > 0.85 ? Math.max(0, 1 - (k - 0.85) / 0.15) : 1
    m.scale.setScalar(0.12 * (0.6 + pop * 0.4))
    if (k >= 1) onDone(spark.id)
  })

  return (
    <mesh ref={ref}>
      <sphereGeometry args={[1, 12, 12]} />
      <meshBasicMaterial color={spark.color} transparent opacity={0.95} toneMapped={false} />
    </mesh>
  )
}

export function NotificationOrbs({
  notifications,
  operatorPos,
  onDone,
}: {
  notifications: NotifSpark[]
  operatorPos: React.RefObject<THREE.Vector3>
  onDone: (id: number) => void
}) {
  return (
    <>
      {notifications.map((s) => (
        <Orb key={s.id} spark={s} operatorPos={operatorPos} onDone={onDone} />
      ))}
    </>
  )
}
