// ============================================================================
// JARVIS SPATIAL DASHBOARD — V15 ENTRANCE FURNITURE ("The Threshold")
// World rect: x in [-22, -7.5], z in [-16, -5.5]. Accent cyan / white.
// Room centre ≈ (x -14.75, z -10.75); width 14.5 (x) · depth 10.5 (z).
// Objects render in ABSOLUTE WORLD coords (NOT wrapped in a room-centre group).
// TALL OUTER WALLS: TOP wall z=-16 (door gap at x≈-14.75, faces +z) and
// LEFT wall x=-22 (faces +x). Wall items centred y≈1.0–1.2 so nothing floats.
// V15 ROOM POLISH: geometry scaled ~1.3–1.5x for a larger (~3.2 tall) Operator
// and a near-top-down read; the free-standing access scanner moved off the
// door wall into the room interior (its Interactive position AND avatar anchor
// move together). Wall-mounted door / monitor / weather / lights stay on the
// tall outer walls. Every object is a functional UI element — no decoration.
// ============================================================================
import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { RoundedBox, Text } from '@react-three/drei'
import * as THREE from 'three'
import { PALETTE, WT, ENTRANCE_DOOR_H } from '../sceneConstants'
import { Interactive } from '../Interactive'
import type { RoomFurnitureProps } from '../dollhouseTypes'

// ---- WORLD-COORD WALL ANCHORS for this room ------------------------------
// TOP outer wall sits at z = -16; its INNER face (toward the room interior) is
// at z = -16 + WT/2. Mounted devices hug that face, a hair into the room (+z).
const TOP_WALL_Z = -16 + WT / 2 + 0.02 // ≈ -15.78  (faces +z)
// LEFT outer wall sits at x = -22; its INNER face is at x = -22 + WT/2.
const LEFT_WALL_X = -22 + WT / 2 + 0.02 // ≈ -21.78  (faces +x)

// Door gap centre on the TOP wall.
const DOOR_X = -14.75
const DOOR_H = ENTRANCE_DOOR_H // 1.6 — stays under OW_H (1.7)
const DOOR_CY = DOOR_H / 2 // 0.8

// Free-standing access-scanner pad — pulled into the ROOM INTERIOR (centre-ish)
// instead of hugging the door wall, so the floor reads as occupied.
const SCAN_X = -14.75 // room centre x
const SCAN_Z = -10.6 // ~room centre z (interior, well off the top wall)

// Smart-light button definitions (index i drives layout — no module randomness).
const LIGHT_BUTTONS = [
  { key: 'living', label: 'LIV', color: PALETTE.amber },
  { key: 'office', label: 'OFF', color: PALETTE.cyan },
  { key: 'wellness', label: 'WEL', color: PALETTE.purple },
  { key: 'alloff', label: 'OFF', color: '#334155' },
] as const

export default function EntranceFurniture({ services, mood, ix }: RoomFurnitureProps) {
  // ---- typed refs (all guarded in useFrame) ----
  const doorFrameRef = useRef<THREE.MeshStandardMaterial>(null)
  const doorGlassRef = useRef<THREE.MeshStandardMaterial>(null)
  const tempRef = useRef<THREE.MeshStandardMaterial>(null)
  const weatherRingRef = useRef<THREE.MeshStandardMaterial>(null)
  const sunIconRef = useRef<THREE.MeshStandardMaterial>(null)
  const lightBtnRefs = useRef<(THREE.MeshStandardMaterial | null)[]>([])
  const scanRingRef = useRef<THREE.Mesh>(null)
  const scanMatRef = useRef<THREE.MeshStandardMaterial>(null)

  const weatherAlert = services.weatherAlert || mood === 'warning'

  useFrame((state) => {
    const t = state.clock.getElapsedTime()

    // Front door frame "breathes" a welcome-home pulse; glass shimmers faintly.
    if (doorFrameRef.current) {
      doorFrameRef.current.emissiveIntensity = 2.4 + Math.sin(t * 1.6) * 0.8
    }
    if (doorGlassRef.current) {
      doorGlassRef.current.emissiveIntensity = 0.7 + Math.sin(t * 1.6 + 0.6) * 0.25
    }

    // Environment monitor temp readout — gentle live-screen breathe.
    if (tempRef.current) {
      tempRef.current.emissiveIntensity = 2.0 + Math.sin(t * 1.3) * 0.4
    }

    // Weather-station ring: calm cyan glow, or a fast hot-RED pulse on alert.
    if (weatherRingRef.current) {
      const base = weatherAlert ? 3.4 : 2.6
      const amp = weatherAlert ? 1.6 : 0.5
      const speed = weatherAlert ? 6 : 2
      weatherRingRef.current.emissiveIntensity = base + Math.sin(t * speed) * amp
      const col = weatherAlert ? PALETTE.warningRed : PALETTE.cyan
      weatherRingRef.current.color.set(col)
      weatherRingRef.current.emissive.set(col)
    }
    if (sunIconRef.current) {
      sunIconRef.current.emissiveIntensity = 2.4 + Math.sin(t * 2.4) * 0.6
    }

    // Smart-light buttons softly pulse out of phase (index i → variety).
    lightBtnRefs.current.forEach((m, i) => {
      if (m) m.emissiveIntensity = 2.2 + Math.sin(t * 1.8 + i * 1.3) * 0.5
    })

    // Access scanner: idle breathe; sweeps faster + brighter while a task runs.
    if (scanRingRef.current) {
      const speed = services.taskActive ? 2.6 : 0.9
      const s = 1 + ((t * speed) % 1) * 0.9 // expanding scan ripple
      scanRingRef.current.scale.set(s, s, s)
    }
    if (scanMatRef.current) {
      const phase = (t * (services.taskActive ? 2.6 : 0.9)) % 1
      scanMatRef.current.emissiveIntensity = (services.taskActive ? 3.2 : 2.0) * (1 - phase)
    }
  })

  return (
    <group>
      {/* ============================================================
          1. GLASS FRONT DOOR — TOP wall at the door gap (x≈-14.75).
          Transparent cyan panel + glowing frame that pulses (welcome home).
          Wider/chunkier frame for a near-top-down read; height stays under
          OW_H (1.7) since DOOR_H is fixed. Avatar stands inside, faces -z.
          ============================================================ */}
      <Interactive
        id="entrance-front-door"
        label="Front Door"
        status="Welcome Home"
        position={[DOOR_X, DOOR_CY, TOP_WALL_Z]}
        anchor={{ position: [DOOR_X, 0, -14], rotationY: Math.PI, pose: 'lookout' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={2.0}
      >
        {/* transparent cyan glass panel (wider double-leaf read) */}
        <mesh position={[DOOR_X, DOOR_CY, TOP_WALL_Z]}>
          <planeGeometry args={[3.9, DOOR_H]} />
          <meshStandardMaterial
            ref={doorGlassRef}
            color={PALETTE.cyan}
            emissive={PALETTE.cyan}
            emissiveIntensity={0.7}
            transparent
            opacity={0.16}
            side={THREE.DoubleSide}
            roughness={0.1}
            metalness={0}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
        {/* glowing frame — vertical jambs (chunkier) */}
        {([-2.0, 2.0] as const).map((dx) => (
          <mesh key={`jamb-${dx}`} position={[DOOR_X + dx, DOOR_CY, TOP_WALL_Z + 0.02]} castShadow>
            <boxGeometry args={[0.15, DOOR_H + 0.08, 0.09]} />
            <meshStandardMaterial
              ref={dx < 0 ? doorFrameRef : undefined}
              color={PALETTE.cyan}
              emissive={PALETTE.cyan}
              emissiveIntensity={2.4}
              toneMapped={false}
            />
          </mesh>
        ))}
        {/* glowing frame — top + bottom rails (chunkier) */}
        {([DOOR_H, 0.04] as const).map((ry, i) => (
          <mesh key={`rail-${i}`} position={[DOOR_X, ry, TOP_WALL_Z + 0.02]}>
            <boxGeometry args={[4.1, 0.13, 0.09]} />
            <meshStandardMaterial color={PALETTE.cyan} emissive={PALETTE.cyan} emissiveIntensity={2.4} toneMapped={false} />
          </mesh>
        ))}
        {/* central mullion + handle bar for a crafted glass-door read */}
        <mesh position={[DOOR_X, DOOR_CY, TOP_WALL_Z + 0.015]}>
          <boxGeometry args={[0.07, DOOR_H, 0.07]} />
          <meshStandardMaterial color={PALETTE.cyan} emissive={PALETTE.cyan} emissiveIntensity={2.0} toneMapped={false} />
        </mesh>
        <mesh position={[DOOR_X - 0.6, DOOR_CY, TOP_WALL_Z + 0.06]}>
          <boxGeometry args={[0.07, 0.66, 0.07]} />
          <meshStandardMaterial color={PALETTE.whiteLight} emissive={PALETTE.whiteLight} emissiveIntensity={1.9} toneMapped={false} />
        </mesh>
      </Interactive>

      {/* ============================================================
          2. ENVIRONMENT MONITOR — landscape screen on LEFT wall.
          Scaled up ~1.35x so temp/humidity read clearly. Shows temp (white)
          + humidity (cyan). Faces +x; avatar faces -x. Centred y=1.1.
          ============================================================ */}
      <Interactive
        id="entrance-env-monitor"
        label="Environment Monitor"
        status="22.5C / 48% RH"
        position={[LEFT_WALL_X, 1.1, -8]}
        anchor={{ position: [-20.4, 0, -8], rotationY: -Math.PI / 2, pose: 'point' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.3}
      >
        <group position={[LEFT_WALL_X, 1.1, -8]} rotation={[0, Math.PI / 2, 0]}>
          {/* dark bezel (faces +x after the group's +y rotation) */}
          <RoundedBox args={[2.05, 1.06, 0.08]} radius={0.05} smoothness={4} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.45} metalness={0.5} emissiveIntensity={0} />
          </RoundedBox>
          {/* screen panel */}
          <mesh position={[0, 0, 0.045]}>
            <planeGeometry args={[1.8, 0.82]} />
            <meshStandardMaterial color="#0e2a33" emissive={PALETTE.cyan} emissiveIntensity={0.5} toneMapped={false} />
          </mesh>
          {/* TEMP — large white readout */}
          <Text position={[0, 0.18, 0.066]} fontSize={0.27} color={PALETTE.whiteLight} anchorX="center" anchorY="middle">
            22.5°C
          </Text>
          {/* a thin emissive material we can breathe via tempRef, sits behind the temp text */}
          <mesh position={[0, 0.18, 0.055]}>
            <planeGeometry args={[1.22, 0.36]} />
            <meshStandardMaterial ref={tempRef} color="#0e2a33" emissive={PALETTE.whiteLight} emissiveIntensity={2.0} transparent opacity={0.12} toneMapped={false} />
          </mesh>
          {/* HUMIDITY — cyan readout */}
          <Text position={[0, -0.22, 0.066]} fontSize={0.19} color={PALETTE.cyan} anchorX="center" anchorY="middle">
            48% RH
          </Text>
        </group>
      </Interactive>

      {/* ============================================================
          3. WEATHER STATION — circular wall device on TOP wall, right of
          the door (x≈-10). Scaled up ~1.4x. Glowing ring + sun icon; ring
          pulses RED on alert. Centred y=1.15.
          ============================================================ */}
      <Interactive
        id="entrance-weather-station"
        label="Weather Station"
        status={weatherAlert ? 'Storm Alert' : 'Clear · 23°C'}
        position={[-10, 1.15, TOP_WALL_Z]}
        anchor={{ position: [-10, 0, -14.4], rotationY: Math.PI, pose: 'point' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.2}
      >
        <group position={[-10, 1.15, TOP_WALL_Z]}>
          {/* dark backing disc, flat face toward room (+z) */}
          <mesh rotation={[Math.PI / 2, 0, 0]} castShadow>
            <cylinderGeometry args={[0.5, 0.5, 0.07, 32]} />
            <meshStandardMaterial color={PALETTE.void} roughness={0.7} metalness={0.1} emissiveIntensity={0} />
          </mesh>
          {/* glowing ring (cyan / red on alert) — hole faces +z */}
          <mesh position={[0, 0, 0.045]}>
            <torusGeometry args={[0.4, 0.05, 12, 40]} />
            <meshStandardMaterial ref={weatherRingRef} color={PALETTE.cyan} emissive={PALETTE.cyan} emissiveIntensity={2.6} toneMapped={false} />
          </mesh>
          {/* sun core */}
          <mesh position={[-0.055, 0.03, 0.07]}>
            <circleGeometry args={[0.13, 22]} />
            <meshStandardMaterial ref={sunIconRef} color={PALETTE.amber} emissive={PALETTE.amber} emissiveIntensity={2.4} toneMapped={false} />
          </mesh>
          {/* sun rays (index i → radial variety) */}
          {([0, 1, 2, 3, 4, 5, 6, 7] as const).map((i) => {
            const a = (i / 8) * Math.PI * 2
            return (
              <mesh key={`ray-${i}`} position={[-0.055 + Math.cos(a) * 0.22, 0.03 + Math.sin(a) * 0.22, 0.07]} rotation={[0, 0, a]}>
                <boxGeometry args={[0.1, 0.025, 0.014]} />
                <meshStandardMaterial color={PALETTE.amber} emissive={PALETTE.amber} emissiveIntensity={2.0} toneMapped={false} />
              </mesh>
            )
          })}
          {/* small cloud puffs over the sun */}
          {([[0.18, -0.055, 0.07], [0.25, -0.03, 0.07]] as [number, number, number][]).map((p, i) => (
            <mesh key={`cloud-${i}`} position={p}>
              <circleGeometry args={[0.07 - i * 0.017, 18]} />
              <meshStandardMaterial color={PALETTE.whiteLight} emissive={PALETTE.whiteLight} emissiveIntensity={1.4} toneMapped={false} />
            </mesh>
          ))}
        </group>
      </Interactive>

      {/* ============================================================
          4. SMART LIGHTS PANEL — vertical strip of 4 square buttons on
          the TOP wall (x≈-18). Living(amber)/Office(cyan)/Wellness(purple)/AllOff(dim).
          Scaled up but plate stays 1.2 tall, centred y=1.0 → top 1.6 < OW_H (1.7),
          nothing pokes above the wall. Avatar presses them; faces -z.
          ============================================================ */}
      <Interactive
        id="entrance-smart-lights"
        label="Smart Lights"
        status="4 Scenes"
        position={[-18, 1.0, TOP_WALL_Z]}
        anchor={{ position: [-18, 0, -14.4], rotationY: Math.PI, pose: 'press' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.1}
      >
        {/* centred y=1.0 with a 1.2-tall plate → top at 1.6 < OW_H (1.7); buttons
            widened ~1.4x and the plate broadened so the strip reads clearly. */}
        <group position={[-18, 1.0, TOP_WALL_Z]}>
          {/* dark mounting plate */}
          <RoundedBox args={[0.48, 1.2, 0.07]} radius={0.04} smoothness={4} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.5} metalness={0.4} emissiveIntensity={0} />
          </RoundedBox>
          {/* 4 glowing square buttons stacked vertically (top→bottom), all inside the plate */}
          {LIGHT_BUTTONS.map((b, i) => (
            <mesh key={b.key} position={[0, 0.42 - i * 0.28, 0.055]}>
              <boxGeometry args={[0.31, 0.31, 0.055]} />
              <meshStandardMaterial
                ref={(m) => {
                  lightBtnRefs.current[i] = m
                }}
                color={b.color}
                emissive={b.color}
                emissiveIntensity={b.key === 'alloff' ? 0.3 : 2.2}
                toneMapped={false}
              />
            </mesh>
          ))}
        </group>
      </Interactive>

      {/* ============================================================
          5. ACCESS SCANNER PAD — functional presence / biometric floor pad.
          MOVED into the ROOM INTERIOR (centre ≈ x-14.75, z-10.6) off the door
          wall so the floor reads occupied; scaled up ~1.4x. Operator steps onto
          it to be identified; the scan ring sweeps faster when a task is running.
          Interactive position + avatar anchor both moved (anchor ~1.4 in front,
          y=0, facing -z toward the pad). Clickable.
          ============================================================ */}
      <Interactive
        id="entrance-access-scanner"
        label="Access Scanner"
        status={services.taskActive ? 'Scanning…' : 'Identity: Operator'}
        position={[SCAN_X, 0.05, SCAN_Z]}
        anchor={{ position: [SCAN_X, 0, SCAN_Z + 1.4], rotationY: Math.PI, pose: 'lookout' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.7}
      >
        <group position={[SCAN_X, 0, SCAN_Z]}>
          {/* dark scanner base plate on the floor (bottom at y=0) */}
          <RoundedBox args={[3.6, 0.08, 1.85]} radius={0.08} smoothness={4} position={[0, 0.04, 0]} castShadow receiveShadow>
            <meshStandardMaterial color={PALETTE.void} roughness={0.85} metalness={0.2} emissiveIntensity={0} />
          </RoundedBox>
          {/* glowing identity grid line (status strip) */}
          <mesh position={[0, 0.085, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[0.47, 0.58, 40]} />
            <meshStandardMaterial color={PALETTE.cyan} emissive={PALETTE.cyan} emissiveIntensity={2.0} toneMapped={false} side={THREE.DoubleSide} />
          </mesh>
          {/* expanding scan ripple ring (animated via scanRingRef / scanMatRef) */}
          <mesh ref={scanRingRef} position={[0, 0.087, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[0.64, 0.72, 40]} />
            <meshStandardMaterial ref={scanMatRef} color={PALETTE.cyan} emissive={PALETTE.cyan} emissiveIntensity={2.0} transparent opacity={0.85} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
          </mesh>
          {/* status readout on the pad, readable from inside the room (+z) */}
          <Text position={[0, 0.088, 0.66]} rotation={[-Math.PI / 2, 0, 0]} fontSize={0.22} color={PALETTE.cyan} anchorX="center" anchorY="middle" letterSpacing={0.12}>
            ACCESS
          </Text>
        </group>
      </Interactive>
    </group>
  )
}
