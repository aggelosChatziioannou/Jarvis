// ============================================================================
// JARVIS SPATIAL DASHBOARD — V15 CONTROL ROOM / "THE CORE" FURNITURE
// Room rect: x in [7.5, 22], z in [5.5, 16] (centre ≈ [14.75, 0, 10.75]).
// TALL OUTER WALLS: RIGHT wall x=22, BOTTOM wall z=16. Accent: blue-purple
// #6366f1 + cyan. Moody / important.
//
// Objects render in ABSOLUTE WORLD coordinates (NOT wrapped in a room-centre
// group). Every clickable object is wrapped in <Interactive>. Bottoms of all
// floor objects sit at y=0. Wall-mounted objects centre at y≈1.15 on the TALL
// outer walls only.
//
// FUNCTIONAL OBJECTS (all live UI elements, no decoration):
//   1. CURVED MONITOR WALL — 3 screens (lock / gear / lightbulb) on BOTTOM wall.
//   2. SERVER RACK — tall floor unit on RIGHT wall, 8 LED slots.
//   3. HOLOGRAPHIC CORE TABLE — floating wireframe cube in room centre.
//   4. ENERGY MONITOR — circular dial gauge on RIGHT wall.
// ============================================================================

import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { RoundedBox, Text } from '@react-three/drei'
import * as THREE from 'three'
import { PALETTE } from '../sceneConstants'
import { Interactive } from '../Interactive'
import type { RoomFurnitureProps } from '../dollhouseTypes'

// ---- Room world anchors ----------------------------------------------------
// Room rect x[7.5,22] z[5.5,16], centre ≈ [14.75, 0, 10.75].
// V15 ROOM POLISH: geometry scaled ~1.4x for the larger 3.2-tall Operator and a
// near-top-down read. Free-standing pieces spread across the floor; wall-mounted
// screens/dial stay on the TALL OUTER walls (RIGHT x=22 & BOTTOM z=16).
const BOTTOM_WALL_Z = 16 // tall outer wall (bottom). Monitor wall mounts just in front.
const RIGHT_WALL_X = 22 // tall outer wall (right). Energy dial mounts just in front.
const SCREEN_Z = BOTTOM_WALL_Z - 0.75 // screen face plane (just inside the wall; bigger bezel needs more clearance)
const RACK_X = RIGHT_WALL_X - 0.78 // server-rack body centre — pushed to the RIGHT side wall, away from centre
const RACK_Z = 7.4 // rack sits in the +z-near corner of the right wall (spread off the dial)
const GAUGE_X = RIGHT_WALL_X - 0.26 // wall gauge centre (flush just in front of the 21.8 inner wall face)
const GAUGE_Z = 13.4 // dial mounted lower on the right wall (spread off the rack)
const CORE_X = 14.75 // room centre x — holographic core stays dead-centre
const CORE_Z = 10.75 // room centre z

const ACCENT = PALETTE.controlBlue // #6366f1

export default function ControlFurniture({ services, mood, ix }: RoomFurnitureProps) {
  // ---- typed refs ----------------------------------------------------------
  // Monitor-wall: per-screen emissive screen surfaces + glowing icon glyphs.
  const screenMatRefs = useRef<Array<THREE.MeshStandardMaterial | null>>([])
  const iconMatRefs = useRef<Array<THREE.MeshStandardMaterial | null>>([])
  const gearRef = useRef<THREE.Group>(null) // settings gear (centre screen) spins
  // Server rack LED slots.
  const rackLedRefs = useRef<Array<THREE.MeshStandardMaterial | null>>([])
  // Holographic core cube.
  const coreGroupRef = useRef<THREE.Group>(null) // float bob
  const coreCubeRef = useRef<THREE.LineSegments>(null) // wireframe rotation
  const coreLineMatRef = useRef<THREE.LineBasicMaterial>(null) // brighten / recolor
  const coreInnerRef = useRef<THREE.Mesh>(null) // faint inner solid
  const coreInnerMatRef = useRef<THREE.MeshStandardMaterial>(null)
  // Energy gauge.
  const needleRef = useRef<THREE.Group>(null)
  const gaugeRingRef = useRef<THREE.MeshStandardMaterial>(null)

  // ---- derived live states -------------------------------------------------
  const processing = services.processing
  const moodIsBusy = mood === 'busy'
  const energySpike = services.weatherAlert || mood === 'warning' // gauge runs hot

  // Wireframe cube edges geometry (created once). Scaled up ~1.45x for the bigger core.
  const cubeEdges = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(0.9, 0.9, 0.9)), [])

  // Three monitor-wall screens, in a gentle concave arc on the BOTTOM outer
  // wall. Side screens toe-in (rotationY) + sit slightly nearer the room (z-).
  // x relative to room centre 14.75. glyph: lock / gear / lightbulb.
  // Spread WIDER (±4.6) across the bottom wall so the bigger 2.35-wide bezels read clearly.
  const screens = useMemo(
    () =>
      [
        { id: 'control-security', label: 'Security', x: CORE_X - 4.6, z: SCREEN_Z - 0.24, ry: 0.26, color: PALETTE.cyan, glyph: '\u{1F512}', pose: 'point' as const },
        { id: 'control-settings', label: 'Settings', x: CORE_X, z: SCREEN_Z, ry: 0, color: ACCENT, glyph: '⚙', pose: 'press' as const },
        { id: 'control-devices', label: 'Devices', x: CORE_X + 4.6, z: SCREEN_Z - 0.24, ry: -0.26, color: PALETTE.amber, glyph: '\u{1F4A1}', pose: 'point' as const },
      ] as const,
    [],
  )

  // 8 server-rack LED slots. Index 5 = amber (warning slot), index 2 blinks.
  const rackSlots = useMemo(() => [0, 1, 2, 3, 4, 5, 6, 7] as const, [])

  useFrame((state) => {
    const t = state.clock.getElapsedTime()

    // ---- Monitor wall: subtle scanline flicker + glowing icon breathe ----
    screenMatRefs.current.forEach((mat, i) => {
      if (mat) mat.emissiveIntensity = 1.85 + Math.sin(t * 6 + i * 2.1) * 0.18
    })
    iconMatRefs.current.forEach((mat, i) => {
      if (mat) mat.emissiveIntensity = 3.2 + Math.sin(t * 3 + i) * 0.4
    })
    // Centre "Settings" gear spins continuously; FAST when AI is processing.
    if (gearRef.current) {
      gearRef.current.rotation.z -= (processing ? 2.4 : 0.5) * 0.016
    }

    // ---- Server rack LEDs: cyan healthy, one amber, index 2 blinks ----
    rackLedRefs.current.forEach((mat, i) => {
      if (!mat) return
      if (i === 5) {
        // amber warning slot — steady warm glow
        mat.emissiveIntensity = 2.6 + Math.sin(t * 2.2) * 0.5
      } else if (i === 2) {
        // blinking slot (square-ish pulse via index-offset phase)
        mat.emissiveIntensity = Math.sin(t * 4.5) > 0 ? 4 : 0.4
      } else {
        mat.emissiveIntensity = 2.4 + Math.sin(t * 1.8 + i * 0.7) * 0.4
      }
    })

    // ---- Holographic core cube ----
    if (coreGroupRef.current) {
      const wobble = moodIsBusy ? Math.sin(t * 6) * 0.12 : 0
      coreGroupRef.current.position.y = 1.78 + Math.sin(t * 1.4) * 0.09
      coreGroupRef.current.rotation.z = wobble
    }
    if (coreCubeRef.current) {
      const spin = processing ? 1.9 : 0.6 // FAST when processing
      coreCubeRef.current.rotation.y = t * spin
      coreCubeRef.current.rotation.x = t * spin * 0.62
    }
    // Cube color: amber when mood busy, brighter blue/cyan when processing.
    const coreColor = moodIsBusy ? PALETTE.amber : PALETTE.cyan
    if (coreLineMatRef.current) {
      coreLineMatRef.current.color.set(coreColor)
    }
    if (coreInnerRef.current) {
      coreInnerRef.current.rotation.y = (coreCubeRef.current?.rotation.y ?? 0)
      coreInnerRef.current.rotation.x = (coreCubeRef.current?.rotation.x ?? 0)
    }
    if (coreInnerMatRef.current) {
      coreInnerMatRef.current.color.set(coreColor)
      coreInnerMatRef.current.emissive.set(coreColor)
      coreInnerMatRef.current.emissiveIntensity = processing ? 3.2 + Math.sin(t * 8) * 0.6 : 1.8
    }

    // ---- Energy gauge: needle sweeps; glows amber on spike ----
    if (needleRef.current) {
      // base reading ~0.6 of the arc, gently breathing; pinned high on spike.
      const reading = energySpike ? 0.92 + Math.sin(t * 7) * 0.05 : 0.55 + Math.sin(t * 1.1) * 0.08
      // map 0..1 reading to a -120°..+120° sweep (clamped fan around straight up)
      needleRef.current.rotation.z = (0.5 - reading) * (Math.PI * 1.33)
    }
    if (gaugeRingRef.current) {
      const col = energySpike ? PALETTE.amber : PALETTE.cyan
      gaugeRingRef.current.color.set(col)
      gaugeRingRef.current.emissive.set(col)
      gaugeRingRef.current.emissiveIntensity = energySpike ? 3.6 + Math.sin(t * 6) * 1.2 : 2.2 + Math.sin(t * 1.6) * 0.4
    }
  })

  return (
    <group>
      {/* ============ 1. CURVED MONITOR WALL — 3 screens on BOTTOM outer wall ============ */}
      {/* Each screen is a SEPARATE Interactive. Centred y≈1.15, faces -z into room. */}
      {screens.map((s, i) => (
        <Interactive
          key={s.id}
          id={s.id}
          label={s.label}
          status={s.id === 'control-settings' && processing ? 'processing…' : 'online'}
          position={[s.x, 1.1, s.z]}
          anchor={{ position: [s.x, 0, s.z - 1.4], rotationY: 0, pose: s.pose }}
          ix={ix}
          accent={s.color}
          ringRadius={1.4}
        >
          {/* Group base-rotated by Math.PI so its local +z faces -z (the room
              interior); +s.ry adds the gentle concave toe-in. Bezel/screen/icon
              all sit at +local-z so their lit faces point into the room. */}
          <group position={[s.x, 1.1, s.z]} rotation={[0, Math.PI + s.ry, 0]}>
            {/* Dark chunky bezel (non-emissive). Widened to 2.35; height capped at the 1.2 wall-item limit. */}
            <RoundedBox args={[2.35, 1.2, 0.14]} radius={0.06} smoothness={4} castShadow>
              <meshStandardMaterial color="#0b1220" roughness={0.45} metalness={0.55} emissiveIntensity={0} />
            </RoundedBox>
            {/* Emissive screen surface (faces +local-z → -z into the room). */}
            <mesh position={[0, 0, 0.08]}>
              <planeGeometry args={[2.08, 1.0]} />
              <meshStandardMaterial
                ref={(m) => {
                  screenMatRefs.current[i] = m
                }}
                color="#020617"
                emissive={s.color}
                emissiveIntensity={1.85}
                toneMapped={false}
              />
            </mesh>
            {/* Glowing icon glyph. Centre screen = gear group that spins. */}
            {s.id === 'control-settings' ? (
              <group ref={gearRef} position={[0, 0, 0.11]}>
                <Text fontSize={0.78} anchorX="center" anchorY="middle">
                  {s.glyph}
                  <meshStandardMaterial
                    ref={(m) => {
                      iconMatRefs.current[i] = m
                    }}
                    color={s.color}
                    emissive={s.color}
                    emissiveIntensity={3.2}
                    toneMapped={false}
                  />
                </Text>
              </group>
            ) : (
              <Text position={[0, 0, 0.11]} fontSize={0.72} anchorX="center" anchorY="middle">
                {s.glyph}
                <meshStandardMaterial
                  ref={(m) => {
                    iconMatRefs.current[i] = m
                  }}
                  color={s.color}
                  emissive={s.color}
                  emissiveIntensity={3.2}
                  toneMapped={false}
                />
              </Text>
            )}
          </group>
        </Interactive>
      ))}

      {/* ============ 2. SERVER RACK — tall dark floor unit on RIGHT wall ============ */}
      {/* Operator stands to the -x (interior) side, faces +x toward the rack. */}
      <Interactive
        id="control-server"
        label="Server Status"
        status="8 nodes · 1 warning"
        position={[RACK_X, 1.25, RACK_Z]}
        anchor={{ position: [RACK_X - 1.9, 0, RACK_Z], rotationY: Math.PI / 2, pose: 'reach' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.25}
      >
        {/* Tall dark hero body on the RIGHT wall (bottom on the floor, ~2.5 tall, scaled 1.4x footprint). */}
        <RoundedBox args={[1.05, 2.5, 0.98]} radius={0.06} smoothness={4} position={[RACK_X, 1.25, RACK_Z]} castShadow>
          <meshStandardMaterial color="#0b1220" roughness={0.5} metalness={0.45} emissiveIntensity={0} />
        </RoundedBox>
        {/* 8 horizontal LED slots stacked up the face (faces -x into the room).
            y spans 0.4..2.22 so all 8 slots (incl. recess + bar) stay on the
            2.5-tall body (top LED previously floated above the rack). */}
        {rackSlots.map((n) => {
          const y = 0.4 + n * 0.26
          const isAmber = n === 5
          const col = isAmber ? PALETTE.amber : PALETTE.cyan
          return (
            <group key={n} position={[RACK_X - 0.54, y, RACK_Z]}>
              {/* dark slot recess */}
              <mesh>
                <boxGeometry args={[0.03, 0.2, 0.7]} />
                <meshStandardMaterial color="#06080f" roughness={0.7} emissiveIntensity={0} />
              </mesh>
              {/* emissive LED bar */}
              <mesh position={[-0.018, 0, 0]}>
                <boxGeometry args={[0.02, 0.1, 0.58]} />
                <meshStandardMaterial
                  ref={(m) => {
                    rackLedRefs.current[n] = m
                  }}
                  color={col}
                  emissive={col}
                  emissiveIntensity={2.4}
                  toneMapped={false}
                />
              </mesh>
            </group>
          )
        })}
      </Interactive>

      {/* ============ 3. HOLOGRAPHIC CORE TABLE — room centre ============ */}
      {/* Operator stands ~1.4 in front (toward -z), faces +z toward the table. */}
      <Interactive
        id="control-core"
        label="AI Core"
        status={processing ? 'processing' : moodIsBusy ? 'busy' : 'idle'}
        position={[CORE_X, 1.0, CORE_Z]}
        anchor={{ position: [CORE_X, 0, CORE_Z - 1.9], rotationY: 0, pose: 'reach' }}
        ix={ix}
        accent={ACCENT}
        ringRadius={1.65}
      >
        {/* Square table top (scaled ~1.45x footprint, ~1.1 tall total — hero centrepiece). */}
        <RoundedBox args={[2.15, 0.16, 2.15]} radius={0.06} smoothness={4} position={[CORE_X, 1.04, CORE_Z]} castShadow>
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.5} metalness={0.35} emissiveIntensity={0} />
        </RoundedBox>
        {/* Glowing emitter ring inset on the table surface. */}
        <mesh position={[CORE_X, 1.13, CORE_Z]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.72, 0.035, 12, 44]} />
          <meshStandardMaterial color={ACCENT} emissive={ACCENT} emissiveIntensity={2.4} toneMapped={false} />
        </mesh>
        {/* Central pedestal (non-emissive). */}
        <mesh position={[CORE_X, 0.52, CORE_Z]}>
          <cylinderGeometry args={[0.26, 0.4, 1.04, 16]} />
          <meshStandardMaterial color="#0f172a" roughness={0.45} metalness={0.5} emissiveIntensity={0} />
        </mesh>

        {/* Floating wireframe CUBE + faint inner solid (bobs, spins, recolors). */}
        <group ref={coreGroupRef} position={[CORE_X, 1.78, CORE_Z]}>
          <lineSegments ref={coreCubeRef} geometry={cubeEdges}>
            <lineBasicMaterial ref={coreLineMatRef} color={PALETTE.cyan} toneMapped={false} />
          </lineSegments>
          <mesh ref={coreInnerRef}>
            <boxGeometry args={[0.64, 0.64, 0.64]} />
            <meshStandardMaterial
              ref={coreInnerMatRef}
              color={PALETTE.cyan}
              emissive={PALETTE.cyan}
              emissiveIntensity={1.8}
              transparent
              opacity={0.24}
              toneMapped={false}
            />
          </mesh>
        </group>
      </Interactive>

      {/* ============ 4. ENERGY MONITOR — circular dial gauge on RIGHT wall ============ */}
      {/* Mounted on the TALL right outer wall (x≈22), centred y≈1.15, faces -x.
          Operator stands to the -x (interior) side, faces +x toward the gauge. */}
      <Interactive
        id="control-energy"
        label="Energy"
        status="1.2 kW"
        position={[GAUGE_X, 1.1, GAUGE_Z]}
        anchor={{ position: [GAUGE_X - 1.9, 0, GAUGE_Z], rotationY: Math.PI / 2, pose: 'point' }}
        ix={ix}
        accent={PALETTE.amber}
        ringRadius={1.0}
      >
        {/* Group oriented so its local +z faces -x into the room (rotationY -90°).
            Disc kept at radius 0.6 (=1.2 tall, the wall-item cap); internals + glows
            scaled up for a clear near-top-down read. */}
        <group position={[GAUGE_X, 1.1, GAUGE_Z]} rotation={[0, -Math.PI / 2, 0]}>
          {/* Dark backing disc (flat face toward room). */}
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.6, 0.6, 0.09, 40]} />
            <meshStandardMaterial color="#0b1220" roughness={0.5} metalness={0.4} emissiveIntensity={0} />
          </mesh>
          {/* Glowing outer dial ring (amber on spike, cyan otherwise). */}
          <mesh position={[0, 0, 0.06]}>
            <torusGeometry args={[0.55, 0.05, 12, 48]} />
            <meshStandardMaterial
              ref={gaugeRingRef}
              color={PALETTE.cyan}
              emissive={PALETTE.cyan}
              emissiveIntensity={2.2}
              toneMapped={false}
            />
          </mesh>
          {/* Tick marks fanning around the upper arc. */}
          {([0, 1, 2, 3, 4, 5, 6] as const).map((i) => {
            const a = -Math.PI * 0.66 + (i / 6) * (Math.PI * 1.33)
            return (
              <mesh
                key={`tick-${i}`}
                position={[Math.sin(a) * 0.47, Math.cos(a) * 0.47, 0.07]}
                rotation={[0, 0, -a]}
              >
                <boxGeometry args={[0.03, 0.12, 0.015]} />
                <meshStandardMaterial color={PALETTE.whiteLight} emissive={PALETTE.whiteLight} emissiveIntensity={1.9} toneMapped={false} />
              </mesh>
            )
          })}
          {/* Needle (pivots at the dial centre; rotation.z driven by reading). */}
          <group ref={needleRef} position={[0, 0, 0.09]}>
            <mesh position={[0, 0.24, 0]}>
              <boxGeometry args={[0.05, 0.5, 0.015]} />
              <meshStandardMaterial color={ACCENT} emissive={ACCENT} emissiveIntensity={3.4} toneMapped={false} />
            </mesh>
          </group>
          {/* Centre hub (cylinder axis turned to face the room: rotate the mesh). */}
          <mesh position={[0, 0, 0.1]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.1, 0.1, 0.05, 20]} />
            <meshStandardMaterial color={PALETTE.whiteLight} emissive={PALETTE.whiteLight} emissiveIntensity={2.2} toneMapped={false} />
          </mesh>
          {/* "1.2 kW" readout below the needle. */}
          <Text position={[0, -0.3, 0.09]} fontSize={0.2} color={PALETTE.whiteLight} anchorX="center" anchorY="middle">
            1.2 kW
          </Text>
        </group>
      </Interactive>
    </group>
  )
}
