// ============================================================================
// JARVIS V15 — THE OPERATOR (hero avatar)
// Walks to the active object's anchor (click), idles + wanders the atrium,
// head-tracks hovered objects, recolors by mood, and publishes its world
// position each frame (for notification orbs).
// ============================================================================
import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { RoundedBox, Outlines } from '@react-three/drei'
import * as THREE from 'three'
import { PALETTE, AVATAR_HEIGHT, MOOD_COLOR, ATRIUM_HOME, OPERATOR_SPEED, roomKeyAt, findRoomPath } from './sceneConstants'
import type { OperatorPose } from './sceneConstants'
import type { ActiveTarget, HoveredObject, SystemMood } from './dollhouseTypes'
import { shouldFireArrival } from './furnitureActions'

const SCALE = AVATAR_HEIGHT / 1.5
const LEG_H = 0.30 * SCALE
const LEG_R = 0.085 * SCALE
const TORSO_W = 0.46 * SCALE
const TORSO_H = 0.42 * SCALE
const TORSO_D = 0.30 * SCALE
const HEAD_R = 0.30 * SCALE
const ARM_LEN = 0.34 * SCALE
const ARM_R = 0.07 * SCALE
const HIP_Y = LEG_H
const TORSO_CY = HIP_Y + TORSO_H / 2
const NECK_Y = HIP_Y + TORSO_H
const HEAD_CY = NECK_Y + HEAD_R * 0.92
const SHOULDER_Y = TORSO_CY + TORSO_H * 0.30

const _dir = new THREE.Vector3()

interface PoseSpec {
  bodyY: number
  hipBend: number
  legSpread: number
  larm: [number, number, number]
  rarm: [number, number, number]
  headPitch: number
}
function poseFor(pose: OperatorPose): PoseSpec {
  switch (pose) {
    case 'sit':
    case 'type':
      return { bodyY: -LEG_H * 0.78, hipBend: 1.15, legSpread: 0.12, larm: [0.8, 0, 0.12], rarm: [0.8, 0, -0.12], headPitch: 0.08 }
    case 'reach':
    case 'press':
      return { bodyY: 0, hipBend: 0, legSpread: 0.06, larm: [0.1, 0, 0.15], rarm: [-1.6, 0, -0.15], headPitch: -0.05 }
    case 'point':
      return { bodyY: 0, hipBend: 0, legSpread: 0.06, larm: [0.1, 0, 0.12], rarm: [-1.4, -0.5, -0.2], headPitch: -0.04 }
    case 'cross':
      return { bodyY: 0, hipBend: 0, legSpread: 0.05, larm: [-1.25, 0.55, 0.2], rarm: [-1.25, -0.55, -0.2], headPitch: 0.02 }
    case 'lookout':
      return { bodyY: 0, hipBend: 0, legSpread: 0.07, larm: [0.12, 0, 0.12], rarm: [0.12, 0, -0.12], headPitch: -0.22 }
    default:
      return { bodyY: 0, hipBend: 0, legSpread: 0.05, larm: [0.08, 0, 0.1], rarm: [0.08, 0, -0.1], headPitch: 0 }
  }
}
const damp = (c: number, t: number, f: number) => c + (t - c) * f

function Ghost({ opacity, glow }: { opacity: number; glow: string }) {
  return (
    <group>
      <mesh position={[0, TORSO_CY, 0]}>
        <boxGeometry args={[TORSO_W, TORSO_H, TORSO_D]} />
        <meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={0.6} transparent opacity={opacity} depthWrite={false} />
      </mesh>
      <mesh position={[0, HEAD_CY, 0]}>
        <boxGeometry args={[HEAD_R * 1.7, HEAD_R * 1.7, HEAD_R * 1.7]} />
        <meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={0.6} transparent opacity={opacity} depthWrite={false} />
      </mesh>
    </group>
  )
}

export interface OperatorProps {
  activeTarget: ActiveTarget | null
  mood: SystemMood
  hovered: HoveredObject | null
  operatorPos: React.RefObject<THREE.Vector3 | null>
  onArrive?: (id: string) => void
}

export default function OperatorCharacter({ activeTarget, mood, hovered, operatorPos, onArrive }: OperatorProps) {
  const glow = MOOD_COLOR[mood] ?? PALETTE.cyan

  const root = useRef<THREE.Group>(null)
  const bodyGroup = useRef<THREE.Group>(null)
  const headRef = useRef<THREE.Group>(null)
  const leftLeg = useRef<THREE.Group>(null)
  const rightLeg = useRef<THREE.Group>(null)
  const leftArm = useRef<THREE.Group>(null)
  const rightArm = useRef<THREE.Group>(null)
  const reactorMat = useRef<THREE.MeshStandardMaterial>(null)
  const haloMat = useRef<THREE.MeshStandardMaterial>(null)
  const trail0 = useRef<THREE.Group>(null)
  const trail1 = useRef<THREE.Group>(null)
  const trail2 = useRef<THREE.Group>(null)

  // Walk path (door waypoints + final anchor), built when the destination changes.
  const path = useRef<THREE.Vector3[]>([])
  const pathIdx = useRef(0)
  const lastDest = useRef<string | null>(null)
  const firedNonce = useRef<number | null>(null)
  const onArriveRef = useRef(onArrive)
  onArriveRef.current = onArrive

  const pose: OperatorPose = activeTarget ? activeTarget.pose : 'idle'
  const ps = useMemo(() => poseFor(pose), [pose])

  useFrame((stateCtx, delta) => {
    const t = stateCtx.clock.getElapsedTime()
    const g = root.current
    if (!g) return
    const d = Math.min(0.05, delta)

    const frozen = mood === 'warning'

    // ----- (re)build the walk path when the destination changes -----
    const destId = activeTarget ? activeTarget.id : '__idle__'
    if (destId !== lastDest.current) {
      lastDest.current = destId
      const fromRoom = roomKeyAt([g.position.x, 0, g.position.z])
      const toRoom = activeTarget ? roomKeyAt(activeTarget.position) : 'atrium'
      const finalPt = activeTarget ? activeTarget.position : ATRIUM_HOME
      const doors = findRoomPath(fromRoom, toRoom)
      path.current = [...doors, finalPt].map((p) => new THREE.Vector3(p[0], 0, p[2]))
      pathIdx.current = 0
    }

    // ----- constant-speed walk along the path (door -> door -> anchor) -----
    let isWalking = false
    _dir.set(0, 0, 0)
    if (!frozen && path.current.length) {
      const lastIdx = path.current.length - 1
      const wp = path.current[Math.min(pathIdx.current, lastIdx)]
      _dir.set(wp.x - g.position.x, 0, wp.z - g.position.z)
      const dist = _dir.length()
      const arrivedFinal = pathIdx.current >= lastIdx && dist < 0.2
      if (arrivedFinal && activeTarget) {
        const nonce = activeTarget.nonce ?? 0
        if (shouldFireArrival(firedNonce.current, true, nonce)) {
          firedNonce.current = nonce
          onArriveRef.current?.(activeTarget.id)
        }
      }
      if (!arrivedFinal) {
        isWalking = pathIdx.current < lastIdx || dist > 0.25
        const step = OPERATOR_SPEED * d
        if (dist <= step) {
          g.position.x = wp.x
          g.position.z = wp.z
          if (pathIdx.current < lastIdx) pathIdx.current++
        } else if (dist > 1e-5) {
          g.position.x += (_dir.x / dist) * step
          g.position.z += (_dir.z / dist) * step
        }
      }
    }

    // ----- facing: toward movement while walking, else anchor / hovered -----
    let desiredYaw = g.rotation.y
    if (isWalking && _dir.lengthSq() > 1e-4) {
      desiredYaw = Math.atan2(_dir.x, _dir.z)
    } else if (activeTarget) {
      desiredYaw = activeTarget.rotationY
    } else if (hovered) {
      const hx = hovered.position[0] - g.position.x
      const hz = hovered.position[2] - g.position.z
      if (hx * hx + hz * hz > 1e-3) desiredYaw = Math.atan2(hx, hz)
    }
    let dRot = desiredYaw - g.rotation.y
    dRot = Math.atan2(Math.sin(dRot), Math.cos(dRot))
    g.rotation.y += dRot * Math.min(1, d * 6)

    // publish world position (chest height) for notification orbs
    if (operatorPos.current) operatorPos.current.set(g.position.x, 1.4, g.position.z)

    // ----- body breathing + pose vertical -----
    if (bodyGroup.current) {
      const breathe = frozen ? 1 : 0.98 + Math.sin((t * 2 * Math.PI) / 3) * 0.02
      bodyGroup.current.scale.setScalar(breathe)
      bodyGroup.current.position.y = damp(bodyGroup.current.position.y, isWalking ? 0 : ps.bodyY, 0.1)
    }

    // ----- limbs -----
    const stride = Math.sin(t * 9) * 0.5
    if (leftLeg.current && rightLeg.current && leftArm.current && rightArm.current) {
      if (isWalking) {
        leftLeg.current.rotation.x = damp(leftLeg.current.rotation.x, stride, 0.4)
        rightLeg.current.rotation.x = damp(rightLeg.current.rotation.x, -stride, 0.4)
        leftArm.current.rotation.set(damp(leftArm.current.rotation.x, -stride + 0.1, 0.4), 0, 0.1)
        rightArm.current.rotation.set(damp(rightArm.current.rotation.x, stride + 0.1, 0.4), 0, -0.1)
        leftLeg.current.rotation.z = damp(leftLeg.current.rotation.z, 0.05, 0.2)
        rightLeg.current.rotation.z = damp(rightLeg.current.rotation.z, -0.05, 0.2)
      } else {
        leftLeg.current.rotation.x = damp(leftLeg.current.rotation.x, ps.hipBend, 0.12)
        rightLeg.current.rotation.x = damp(rightLeg.current.rotation.x, ps.hipBend, 0.12)
        leftLeg.current.rotation.z = damp(leftLeg.current.rotation.z, ps.legSpread, 0.12)
        rightLeg.current.rotation.z = damp(rightLeg.current.rotation.z, -ps.legSpread, 0.12)
        // typing wiggle
        const wig = pose === 'type' ? Math.sin(t * 12) * 0.12 : 0
        leftArm.current.rotation.set(damp(leftArm.current.rotation.x, ps.larm[0] + wig, 0.14), ps.larm[1], ps.larm[2])
        rightArm.current.rotation.set(damp(rightArm.current.rotation.x, ps.rarm[0] - wig, 0.14), ps.rarm[1], ps.rarm[2])
      }
    }

    // ----- head -----
    if (headRef.current) {
      const processingTilt = mood === 'processing' ? -0.12 : 0
      const successDip = mood === 'success' ? Math.max(0, Math.sin(t * 2)) * 0.18 : 0
      const targetPitch = frozen ? ps.headPitch : ps.headPitch + processingTilt + successDip
      headRef.current.rotation.x = damp(headRef.current.rotation.x, targetPitch, 0.1)
      const canLook = !frozen && !isWalking && pose !== 'sit' && pose !== 'type'
      const yaw = canLook ? Math.sin(t * 0.5) * 0.12 : 0
      headRef.current.rotation.y = damp(headRef.current.rotation.y, yaw, 0.05)
    }

    // ----- reactor + halo pulse -----
    const speed = mood === 'processing' ? Math.PI : Math.PI
    if (reactorMat.current) {
      const amp = frozen ? 0 : 1.25
      reactorMat.current.emissiveIntensity = 3.75 + Math.sin(t * speed) * amp
    }
    if (haloMat.current) {
      haloMat.current.emissiveIntensity = 2.0 + Math.sin(t * speed) * 0.6
    }

    // ----- motion trail -----
    const moving = isWalking && _dir.lengthSq() > 1e-4
    const back = _dir.clone().multiplyScalar(moving ? -1 : 0)
    if (moving) back.normalize().multiplyScalar(-1)
    const setTrail = (r: React.RefObject<THREE.Group | null>, k: number) => {
      const tg = r.current
      if (!tg) return
      tg.visible = moving
      if (moving) tg.position.set(back.x * k, 0, back.z * k)
    }
    setTrail(trail0, 0.35)
    setTrail(trail1, 0.7)
    setTrail(trail2, 1.05)
  })

  const bodyColor = PALETTE.slateDark
  const ot = 0.06

  return (
    <group ref={root} position={[0, 0, 0]}>
      <group ref={trail0}><Ghost opacity={0.2} glow={glow} /></group>
      <group ref={trail1}><Ghost opacity={0.12} glow={glow} /></group>
      <group ref={trail2}><Ghost opacity={0.06} glow={glow} /></group>

      {/* floor halo */}
      <group position={[0, 0.05, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <mesh>
          <circleGeometry args={[0.55 * SCALE, 48]} />
          <meshStandardMaterial ref={haloMat} color={glow} emissive={glow} emissiveIntensity={2.2} transparent opacity={0.22} toneMapped={false} depthWrite={false} />
        </mesh>
        <mesh position={[0, 0, 0.001]}>
          <ringGeometry args={[0.58 * SCALE, 0.66 * SCALE, 48]} />
          <meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={3} transparent opacity={0.6} toneMapped={false} depthWrite={false} />
        </mesh>
      </group>

      <group ref={bodyGroup}>
        {/* legs */}
        <group ref={leftLeg} position={[-TORSO_W * 0.28, HIP_Y, 0]}>
          <RoundedBox args={[LEG_R * 2, LEG_H, LEG_R * 2]} radius={LEG_R * 0.6} smoothness={4} position={[0, -LEG_H / 2, 0]}>
            <meshStandardMaterial color={bodyColor} roughness={0.6} emissiveIntensity={0} />
            <Outlines thickness={ot} color={glow} />
          </RoundedBox>
          <mesh position={[0, -LEG_H * 0.55, LEG_R * 0.6]}><sphereGeometry args={[LEG_R * 0.5, 10, 10]} /><meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={4} /></mesh>
        </group>
        <group ref={rightLeg} position={[TORSO_W * 0.28, HIP_Y, 0]}>
          <RoundedBox args={[LEG_R * 2, LEG_H, LEG_R * 2]} radius={LEG_R * 0.6} smoothness={4} position={[0, -LEG_H / 2, 0]}>
            <meshStandardMaterial color={bodyColor} roughness={0.6} emissiveIntensity={0} />
            <Outlines thickness={ot} color={glow} />
          </RoundedBox>
          <mesh position={[0, -LEG_H * 0.55, LEG_R * 0.6]}><sphereGeometry args={[LEG_R * 0.5, 10, 10]} /><meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={4} /></mesh>
        </group>

        {/* torso */}
        <group>
          <RoundedBox args={[TORSO_W, TORSO_H, TORSO_D]} radius={0.09} smoothness={4} position={[0, TORSO_CY, 0]} castShadow>
            <meshStandardMaterial color={bodyColor} roughness={0.6} emissiveIntensity={0} />
            <Outlines thickness={ot} color={glow} />
          </RoundedBox>
          {[-1, 1].map((s) => (
            <RoundedBox key={s} args={[ARM_R * 2.6, ARM_R * 1.7, TORSO_D * 1.05]} radius={ARM_R * 0.7} smoothness={4} position={[s * (TORSO_W / 2 + ARM_R * 0.1), SHOULDER_Y + ARM_R * 0.4, 0]} castShadow>
              <meshStandardMaterial color="#0f172a" roughness={0.6} emissiveIntensity={0} />
              <Outlines thickness={ot * 0.8} color={glow} />
            </RoundedBox>
          ))}
          {/* reactor */}
          <mesh position={[0, TORSO_CY, TORSO_D / 2 + 0.001]}>
            <circleGeometry args={[TORSO_W * 0.22, 28]} />
            <meshStandardMaterial ref={reactorMat} color={glow} emissive={glow} emissiveIntensity={3.75} toneMapped={false} />
          </mesh>
          <mesh position={[0, TORSO_CY, TORSO_D / 2 + 0.0005]}>
            <ringGeometry args={[TORSO_W * 0.24, TORSO_W * 0.3, 28]} />
            <meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={2.5} transparent opacity={0.5} toneMapped={false} />
          </mesh>
          {[-1, 1].map((s) => (
            <mesh key={s} position={[s * TORSO_W / 2, SHOULDER_Y, 0]}><sphereGeometry args={[ARM_R * 0.9, 12, 12]} /><meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={4} /></mesh>
          ))}
        </group>

        {/* arms */}
        <group ref={leftArm} position={[-TORSO_W / 2 - ARM_R * 0.4, SHOULDER_Y, 0]}>
          <RoundedBox args={[ARM_R * 2, ARM_LEN, ARM_R * 2]} radius={ARM_R * 0.6} smoothness={4} position={[0, -ARM_LEN / 2, 0]}>
            <meshStandardMaterial color={bodyColor} roughness={0.6} emissiveIntensity={0} />
            <Outlines thickness={ot} color={glow} />
          </RoundedBox>
          <mesh position={[0, -ARM_LEN * 0.5, ARM_R * 0.6]}><sphereGeometry args={[ARM_R * 0.5, 10, 10]} /><meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={4} /></mesh>
        </group>
        <group ref={rightArm} position={[TORSO_W / 2 + ARM_R * 0.4, SHOULDER_Y, 0]}>
          <RoundedBox args={[ARM_R * 2, ARM_LEN, ARM_R * 2]} radius={ARM_R * 0.6} smoothness={4} position={[0, -ARM_LEN / 2, 0]}>
            <meshStandardMaterial color={bodyColor} roughness={0.6} emissiveIntensity={0} />
            <Outlines thickness={ot} color={glow} />
          </RoundedBox>
          <mesh position={[0, -ARM_LEN * 0.5, ARM_R * 0.6]}><sphereGeometry args={[ARM_R * 0.5, 10, 10]} /><meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={4} /></mesh>
        </group>

        {/* neck */}
        <mesh position={[0, NECK_Y, 0]}><sphereGeometry args={[HEAD_R * 0.28, 14, 14]} /><meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={4} /></mesh>

        {/* head */}
        <group ref={headRef} position={[0, HEAD_CY, 0]}>
          <RoundedBox args={[HEAD_R * 1.7, HEAD_R * 1.66, HEAD_R * 1.66]} radius={HEAD_R * 0.62} smoothness={5} castShadow>
            <meshStandardMaterial color={bodyColor} roughness={0.55} emissiveIntensity={0} />
            <Outlines thickness={ot} color={glow} />
          </RoundedBox>
          <mesh position={[0, HEAD_R * 0.06, HEAD_R * 0.8]}>
            <boxGeometry args={[HEAD_R * 1.5, HEAD_R * 0.62, 0.04]} />
            <meshStandardMaterial color={PALETTE.visorBlack} roughness={0.18} metalness={0.35} emissiveIntensity={0} />
          </mesh>
          <mesh position={[-HEAD_R * 0.33, HEAD_R * 0.07, HEAD_R * 0.83]}><boxGeometry args={[HEAD_R * 0.46, HEAD_R * 0.11, 0.02]} /><meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={6} toneMapped={false} /></mesh>
          <mesh position={[HEAD_R * 0.33, HEAD_R * 0.07, HEAD_R * 0.83]}><boxGeometry args={[HEAD_R * 0.46, HEAD_R * 0.11, 0.02]} /><meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={6} toneMapped={false} /></mesh>
          {[-1, 1].map((s) => (
            <group key={s} position={[s * HEAD_R * 0.86, HEAD_R * 0.02, 0]} rotation={[0, 0, Math.PI / 2]}>
              <mesh><cylinderGeometry args={[HEAD_R * 0.26, HEAD_R * 0.26, HEAD_R * 0.18, 20]} /><meshStandardMaterial color="#0f172a" roughness={0.5} /></mesh>
              <mesh position={[0, s * 0.02, 0]}><cylinderGeometry args={[HEAD_R * 0.13, HEAD_R * 0.13, HEAD_R * 0.22, 16]} /><meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={4} toneMapped={false} /></mesh>
            </group>
          ))}
          <mesh position={[HEAD_R * 0.5, HEAD_R * 0.95, 0]} rotation={[0, 0, -0.18]}><cylinderGeometry args={[0.012, 0.018, HEAD_R * 0.7, 8]} /><meshStandardMaterial color="#0f172a" roughness={0.5} /></mesh>
          <mesh position={[HEAD_R * 0.62, HEAD_R * 1.3, 0]}><sphereGeometry args={[HEAD_R * 0.1, 12, 12]} /><meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={5} toneMapped={false} /></mesh>
        </group>
      </group>
    </group>
  )
}
