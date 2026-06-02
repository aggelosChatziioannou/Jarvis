// ============================================================================
// JARVIS SPATIAL DASHBOARD — V15 STUDIO / DEV LAB FURNITURE
// World rect: x in [-7.5, 7.5], z in [5.5, 16]. TALL OUTER wall = BOTTOM wall
// (z = 16, height OW_H 1.7). Wall-mounted items sit at z ≈ 15.8 (inner face),
// centered y ≈ 1.0-1.2, facing -z into the room. Free-standing kiosks/desks/
// consoles are DISTRIBUTED across the floor interior (bottom y = 0). Everything
// renders in ABSOLUTE WORLD coords (NOT wrapped in a room-centre group).
//
// V15 POLISH PASS: geometry scaled ~1.4x for the larger 3.2-tall Operator and a
// near-top-down camera; free-standing objects spread across the room interior
// (no longer pinned to one wall); the old oversized cyan floor "track" ring is
// gone — replaced by a small (r ≤ 1.0) functional mood pip under the kiosk.
//
// Accent green #10b981 (matrix vibe); cyan #22d3ee for UI rings.
// Functional objects (all live UI elements — no decoration):
//   1. CODE EDITOR — wide desk + 2 monitors (L: scrolling cyan code,
//      R: green terminal text).            [Interactive id="code-editor" pose type]
//   2. SCRIPT TERMINAL — standalone vertical kiosk, blinking green cursor;
//      scrolls fast when services.taskActive. [Interactive id="run-script" pose cross]
//   3. DEBUG DASHBOARD — wall panel, 3 vertical bar graphs (CPU/Mem/Net)
//      cyan→amber→red.                       [Interactive id="system-monitor" pose point]
//   4. AUTOMATION HUB — standalone floor console, 4 toggle switches that glow +
//      dip when toggled (Backup/Clean/Update/Custom). [Interactive id="automation" pose press]
// ============================================================================

import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { RoundedBox, Text } from '@react-three/drei'
import * as THREE from 'three'
import { PALETTE, MOOD_COLOR } from '../sceneConstants'
import { Interactive } from '../Interactive'
import type { RoomFurnitureProps } from '../dollhouseTypes'

// Bottom OUTER wall inner face (wall centred at z = 16, thickness 0.4 → face ≈ 15.8).
const WALL_Z = 15.8

export default function StudioFurniture({ services, mood, ix }: RoomFurnitureProps) {
  // ---- typed refs ----------------------------------------------------------
  // 1. Code editor monitors.
  const codeScreenRef = useRef<THREE.MeshStandardMaterial>(null) // left: scrolling cyan code
  const codeLinesRef = useRef<THREE.Group>(null) // left: code-line group (scrolls)
  const termScreenRef = useRef<THREE.MeshStandardMaterial>(null) // right: green terminal
  const termLinesRef = useRef<THREE.Group>(null) // right: terminal-line group (scrolls)
  // 2. Script terminal kiosk.
  const kioskScreenRef = useRef<THREE.MeshStandardMaterial>(null)
  const kioskLinesRef = useRef<THREE.Group>(null)
  const kioskCursorRef = useRef<THREE.MeshStandardMaterial>(null) // blinking green cursor
  // 3. Debug dashboard bar graphs (CPU / Mem / Net).
  const barMeshRefs = useRef<Array<THREE.Mesh | null>>([])
  const barMatRefs = useRef<Array<THREE.MeshStandardMaterial | null>>([])
  // 4. Automation hub toggle switches.
  const toggleKnobRefs = useRef<Array<THREE.Group | null>>([])
  const toggleMatRefs = useRef<Array<THREE.MeshStandardMaterial | null>>([])
  // Mood pip under the kiosk.
  const moodPipRef = useRef<THREE.MeshStandardMaterial>(null)

  const taskActive = services.taskActive
  const moodColor = MOOD_COLOR[mood]
  const moodIsWarning = mood === 'warning'

  // Scrolling code lines for the LEFT editor monitor (varied widths via index i,
  // no module-scope randomness). Each entry: [width, leftX-offset]. (~1.4x scale)
  const codeLines = useMemo(
    () =>
      Array.from({ length: 10 }, (_, i) => {
        const w = 0.25 + ((i * 7) % 5) * 0.085 // 0.25..0.59 deterministic by i
        return { w, x: -0.31 + w / 2 + ((i % 3) * 0.055) }
      }),
    [],
  )
  // Green terminal lines for the RIGHT editor monitor.
  const termLines = useMemo(
    () =>
      Array.from({ length: 10 }, (_, i) => {
        const w = 0.2 + ((i * 5) % 6) * 0.07
        return { w, x: -0.34 + w / 2 }
      }),
    [],
  )
  // Script-terminal kiosk lines.
  const kioskLines = useMemo(
    () =>
      Array.from({ length: 12 }, (_, i) => {
        const w = 0.22 + ((i * 3) % 7) * 0.07
        return { w, x: -0.48 + w / 2 }
      }),
    [],
  )

  // Debug dashboard: three bars (CPU cyan, Mem amber, Net red). Per-bar phase +
  // base colour. Heights animate; colour ramps cyan→amber→red with load. (~1.4x)
  const bars = useMemo(
    () => [
      { label: 'CPU', x: -0.7, color: PALETTE.cyan, phase: 0 },
      { label: 'MEM', x: 0.0, color: PALETTE.amber, phase: 1.9 },
      { label: 'NET', x: 0.7, color: PALETTE.warningRed, phase: 3.6 },
    ],
    [],
  )
  const BAR_MAX_H = 0.74 // max bar height inside the (wall-mounted) panel — keeps the panel ≤ 1.2 tall so it fits the 1.7 outer wall

  // Automation hub: four toggle switches. Two default-ON via index parity so
  // they read as a real config panel (no randomness).
  const toggles = useMemo(
    () => [
      { label: 'BACKUP', on: true },
      { label: 'CLEAN', on: false },
      { label: 'UPDATE', on: true },
      { label: 'CUSTOM', on: false },
    ],
    [],
  )

  useFrame((state) => {
    const t = state.clock.getElapsedTime()

    // ---- 1. CODE EDITOR — left monitor: cyan code scrolls upward, loops. ----
    if (codeLinesRef.current) {
      // wrap over a 1.2 tall window (~1.4x)
      codeLinesRef.current.position.y = ((t * 0.22) % 1.2) - 0.6
    }
    if (codeScreenRef.current) {
      codeScreenRef.current.emissiveIntensity = 1.9 + Math.sin(t * 5) * 0.18
    }
    // ---- 1. CODE EDITOR — right monitor: green terminal scrolls (slower). ----
    if (termLinesRef.current) {
      termLinesRef.current.position.y = ((t * 0.17) % 1.2) - 0.6
    }
    if (termScreenRef.current) {
      termScreenRef.current.emissiveIntensity = 1.9 + Math.sin(t * 4 + 1.3) * 0.16
    }

    // ---- 2. SCRIPT TERMINAL kiosk: scroll speed jumps when a task is active. ----
    if (kioskLinesRef.current) {
      const speed = taskActive ? 1.26 : 0.2
      kioskLinesRef.current.position.y = ((t * speed) % 1.4) - 0.7
    }
    if (kioskScreenRef.current) {
      kioskScreenRef.current.emissiveIntensity = (taskActive ? 2.6 : 1.9) + Math.sin(t * 6) * 0.2
    }
    if (kioskCursorRef.current) {
      // square-wave blink; faster + brighter while running
      const rate = taskActive ? 6 : 2.6
      const on = Math.sin(t * rate) > 0
      kioskCursorRef.current.emissiveIntensity = on ? (taskActive ? 5 : 3.4) : 0.3
    }

    // ---- 3. DEBUG DASHBOARD: bars rise/fall; colour ramps with load. ----
    bars.forEach((b, i) => {
      const mesh = barMeshRefs.current[i]
      const mat = barMatRefs.current[i]
      // load 0..1 (sine per bar; warning mood pins them high & hot)
      const wave = (Math.sin(t * (1.4 + i * 0.5) + b.phase) + 1) / 2
      const load = moodIsWarning ? 0.78 + wave * 0.22 : 0.25 + wave * 0.6
      const h = Math.max(0.04, load * BAR_MAX_H)
      if (mesh) {
        mesh.scale.y = h / BAR_MAX_H
        // grow upward from the panel base (bar pivot is its centre)
        mesh.position.y = h / 2
      }
      if (mat) {
        // colour ramp: low→cyan, mid→amber, high→red
        const col = load > 0.78 ? PALETTE.warningRed : load > 0.5 ? PALETTE.amber : PALETTE.cyan
        mat.color.set(col)
        mat.emissive.set(col)
        mat.emissiveIntensity = 2.2 + load * 2.2
      }
    })

    // ---- 4. AUTOMATION HUB: toggled-ON knobs glow + sit dipped/forward. ----
    toggles.forEach((tog, i) => {
      const knob = toggleKnobRefs.current[i]
      const mat = toggleMatRefs.current[i]
      const isOn = tog.on
      if (knob) {
        // slide the knob along its track; ON = dipped down + pushed to +x end (~1.4x)
        const targetX = isOn ? 0.1 : -0.1
        knob.position.x += (targetX - knob.position.x) * 0.15
        const targetY = isOn ? -0.017 : 0.017 // ON dips into the panel
        knob.position.y += (targetY - knob.position.y) * 0.15
      }
      if (mat) {
        const base = isOn ? 3.2 : 0.5
        mat.emissiveIntensity = isOn ? base + Math.sin(t * 3 + i) * 0.4 : base
        const col = isOn ? PALETTE.green : '#1e293b'
        mat.color.set(col)
        mat.emissive.set(col)
      }
    })

    // ---- mood pip under the kiosk: gentle breathing glow, recolours with mood. ----
    if (moodPipRef.current) {
      moodPipRef.current.color.set(moodColor)
      moodPipRef.current.emissive.set(moodColor)
      moodPipRef.current.emissiveIntensity = (moodIsWarning ? 2.4 : 1.8) + Math.sin(t * 2) * 0.3
    }
  })

  return (
    <group>
      {/* ===================================================================== */}
      {/* 1. CODE EDITOR — wide free-standing desk in the LEFT-FRONT interior,   */}
      {/* + 2 monitors. Desk centred at world x=-3.8, z≈9.0. Operator stands IN  */}
      {/* FRONT (toward -z) facing +z toward the monitors (rotationY = 0), pose  */}
      {/* 'type'. Scaled ~1.4x. (monitors sit on the far edge of the desk top)   */}
      {/* ===================================================================== */}
      <Interactive
        id="code-editor"
        label="Code Editor"
        status={services.gmailUnread > 0 ? 'Build OK • 2 monitors' : 'Build OK'}
        position={[-3.8, 0.85, 8.9]}
        anchor={{ position: [-3.8, 0, 7.5], rotationY: 0, pose: 'type' }}
        ix={ix}
        accent={PALETTE.green}
        ringRadius={2.3}
      >
        {/* desk top */}
        <RoundedBox args={[5.0, 0.14, 1.35]} radius={0.05} smoothness={4} position={[-3.8, 0.85, 9.0]} castShadow>
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.55} metalness={0.25} emissiveIntensity={0} />
        </RoundedBox>
        {/* four thin legs */}
        {(
          [
            [-6.0, 0.42, 8.55],
            [-1.6, 0.42, 8.55],
            [-6.0, 0.42, 9.45],
            [-1.6, 0.42, 9.45],
          ] as [number, number, number][]
        ).map((p, i) => (
          <mesh key={`desk-leg-${i}`} position={p} castShadow>
            <boxGeometry args={[0.1, 0.85, 0.1]} />
            <meshStandardMaterial color="#0f172a" roughness={0.6} metalness={0.3} emissiveIntensity={0} />
          </mesh>
        ))}

        {/* --- LEFT MONITOR (scrolling cyan code) --- */}
        <group position={[-4.95, 1.62, 9.35]}>
          {/* stand */}
          <mesh position={[0, -0.58, 0]}>
            <cylinderGeometry args={[0.07, 0.11, 0.7, 12]} />
            <meshStandardMaterial color="#0f172a" metalness={0.5} roughness={0.4} emissiveIntensity={0} />
          </mesh>
          {/* dark bezel */}
          <RoundedBox args={[1.34, 0.92, 0.07]} radius={0.035} smoothness={4} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.45} metalness={0.55} emissiveIntensity={0} />
          </RoundedBox>
          {/* emissive screen surface (faces -z into room) */}
          <mesh position={[0, 0, -0.04]}>
            <planeGeometry args={[1.18, 0.78]} />
            <meshStandardMaterial
              ref={codeScreenRef}
              color="#04141a"
              emissive={PALETTE.cyan}
              emissiveIntensity={1.9}
              toneMapped={false}
            />
          </mesh>
          {/* scrolling cyan code lines (clipped visually by the bezel window) */}
          <group ref={codeLinesRef} position={[0, 0, -0.045]}>
            {codeLines.map((l, i) => (
              <mesh key={`code-${i}`} position={[l.x, 0.56 - i * 0.12, 0]}>
                <planeGeometry args={[l.w, 0.036]} />
                <meshStandardMaterial color={PALETTE.cyan} emissive={PALETTE.cyan} emissiveIntensity={3} toneMapped={false} />
              </mesh>
            ))}
          </group>
        </group>

        {/* --- RIGHT MONITOR (green terminal) --- */}
        <group position={[-2.65, 1.62, 9.35]}>
          {/* stand */}
          <mesh position={[0, -0.58, 0]}>
            <cylinderGeometry args={[0.07, 0.11, 0.7, 12]} />
            <meshStandardMaterial color="#0f172a" metalness={0.5} roughness={0.4} emissiveIntensity={0} />
          </mesh>
          {/* dark bezel */}
          <RoundedBox args={[1.34, 0.92, 0.07]} radius={0.035} smoothness={4} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.45} metalness={0.55} emissiveIntensity={0} />
          </RoundedBox>
          {/* emissive green terminal screen */}
          <mesh position={[0, 0, -0.04]}>
            <planeGeometry args={[1.18, 0.78]} />
            <meshStandardMaterial
              ref={termScreenRef}
              color="#03140d"
              emissive={PALETTE.green}
              emissiveIntensity={1.9}
              toneMapped={false}
            />
          </mesh>
          {/* prompt glyph (steady green) */}
          <Text position={[-0.48, 0.31, -0.045]} fontSize={0.1} color={PALETTE.green} anchorX="left" anchorY="middle">
            {'>_'}
          </Text>
          {/* scrolling green terminal lines */}
          <group ref={termLinesRef} position={[0, 0, -0.045]}>
            {termLines.map((l, i) => (
              <mesh key={`term-${i}`} position={[l.x, 0.56 - i * 0.12, 0]}>
                <planeGeometry args={[l.w, 0.034]} />
                <meshStandardMaterial color={PALETTE.green} emissive={PALETTE.green} emissiveIntensity={2.8} toneMapped={false} />
              </mesh>
            ))}
          </group>
        </group>
      </Interactive>

      {/* ===================================================================== */}
      {/* 4. AUTOMATION HUB — standalone floor console in the RIGHT-FRONT        */}
      {/* interior (4 toggles). Centred at world x=3.6, z≈8.6 on a short plinth. */}
      {/* Operator stands in front facing +z (rotationY = 0), pose 'press'.      */}
      {/* Scaled ~1.4x; console top ≈ y 1.0 (free-standing ≤ 1.3 tall).          */}
      {/* ===================================================================== */}
      <Interactive
        id="automation"
        label="Automation"
        status={`${toggles.filter((x) => x.on).length}/4 active`}
        position={[3.6, 0.95, 8.6]}
        anchor={{ position: [3.6, 0, 7.2], rotationY: 0, pose: 'press' }}
        ix={ix}
        accent={PALETTE.green}
        ringRadius={1.15}
      >
        {/* plinth base on the floor */}
        <RoundedBox args={[1.15, 0.86, 0.78]} radius={0.06} smoothness={4} position={[3.6, 0.43, 8.6]} castShadow>
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.6} metalness={0.3} emissiveIntensity={0} />
        </RoundedBox>
        {/* angled console body resting on the plinth (plinth top ≈ y 0.86) */}
        <group position={[3.6, 0.95, 8.55]} rotation={[-0.42, 0, 0]}>
          {/* panel slab */}
          <RoundedBox args={[1.3, 0.09, 0.7]} radius={0.04} smoothness={4} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.45} metalness={0.5} emissiveIntensity={0} />
          </RoundedBox>
          {/* four toggle switches in a row (label + track + sliding knob) */}
          {toggles.map((tog, i) => {
            const tx = (i - 1.5) * 0.3
            return (
              <group key={`tog-${i}`} position={[tx, 0.05, 0.03]}>
                {/* recessed track */}
                <mesh position={[0, 0, 0.085]}>
                  <boxGeometry args={[0.23, 0.017, 0.1]} />
                  <meshStandardMaterial color="#0f172a" roughness={0.6} metalness={0.3} emissiveIntensity={0} />
                </mesh>
                {/* sliding glowing knob (animated x/y by useFrame) */}
                <group
                  ref={(g) => {
                    toggleKnobRefs.current[i] = g
                  }}
                  position={[tog.on ? 0.1 : -0.1, 0, 0.085]}
                >
                  <mesh>
                    <cylinderGeometry args={[0.05, 0.05, 0.07, 16]} />
                    <meshStandardMaterial
                      ref={(m) => {
                        toggleMatRefs.current[i] = m
                      }}
                      color={tog.on ? PALETTE.green : '#1e293b'}
                      emissive={tog.on ? PALETTE.green : '#1e293b'}
                      emissiveIntensity={tog.on ? 3.2 : 0.5}
                      toneMapped={false}
                    />
                  </mesh>
                </group>
                {/* switch label */}
                <Text position={[0, 0, -0.11]} rotation={[-Math.PI / 2, 0, 0]} fontSize={0.05} color={PALETTE.whiteLight} anchorX="center" anchorY="middle">
                  {tog.label}
                </Text>
              </group>
            )
          })}
        </group>
      </Interactive>

      {/* ===================================================================== */}
      {/* 3. DEBUG DASHBOARD — wall panel on BOTTOM outer wall (3 bar graphs)    */}
      {/* Mounted at world z≈15.8, centred y=1.1, panel HEIGHT 1.18 (≤ 1.2) so   */}
      {/* it fits flush on the 1.7-tall outer wall: world span y[0.51, 1.69] —   */}
      {/* top 1.69 < wall 1.7, bottom 0.51 clears the floor. Faces -z. Operator  */}
      {/* stands in front facing +z (rotationY = 0), pose 'point'. Scaled ~1.4x  */}
      {/* width; height trimmed to respect the wall-item ≤ 1.2 rule.             */}
      {/* ===================================================================== */}
      <Interactive
        id="system-monitor"
        label="System Monitor"
        status={moodIsWarning ? 'LOAD HIGH' : 'CPU / MEM / NET'}
        position={[-2.6, 1.1, WALL_Z]}
        anchor={{ position: [-2.6, 0, 14.4], rotationY: 0, pose: 'point' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.5}
      >
        <group position={[-2.6, 1.1, WALL_Z]}>
          {/* dark panel backing (chunky, non-emissive). Height 1.18 ≤ 1.2. */}
          <RoundedBox args={[2.4, 1.18, 0.11]} radius={0.07} smoothness={4} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.45} metalness={0.55} emissiveIntensity={0} />
          </RoundedBox>
          {/* inset dark screen (faces -z) */}
          <mesh position={[0, 0.03, -0.07]}>
            <planeGeometry args={[2.1, 1.0]} />
            <meshStandardMaterial color="#020617" emissive="#06283a" emissiveIntensity={1.0} toneMapped={false} />
          </mesh>
          {/* three vertical bar graphs growing from a common baseline */}
          {bars.map((b, i) => (
            <group key={`bar-${i}`} position={[b.x, -0.34, -0.1]}>
              {/* faint track behind the bar */}
              <mesh position={[0, BAR_MAX_H / 2, 0.007]}>
                <planeGeometry args={[0.25, BAR_MAX_H]} />
                <meshStandardMaterial color="#0f1f2b" emissiveIntensity={0} />
              </mesh>
              {/* the animated bar (scaled in Y by useFrame; pivot at centre) */}
              <mesh
                ref={(m) => {
                  barMeshRefs.current[i] = m
                }}
                position={[0, BAR_MAX_H / 2, 0.017]}
              >
                <boxGeometry args={[0.22, BAR_MAX_H, 0.03]} />
                <meshStandardMaterial
                  ref={(m) => {
                    barMatRefs.current[i] = m
                  }}
                  color={b.color}
                  emissive={b.color}
                  emissiveIntensity={2.6}
                  toneMapped={false}
                />
              </mesh>
              {/* bar label below the baseline (stays inside the panel bottom) */}
              <Text position={[0, -0.16, 0.03]} fontSize={0.13} color={PALETTE.whiteLight} anchorX="center" anchorY="middle">
                {b.label}
              </Text>
            </group>
          ))}
        </group>
      </Interactive>

      {/* ===================================================================== */}
      {/* 2. SCRIPT TERMINAL — standalone vertical kiosk on a floor base         */}
      {/* Free-standing in the RIGHT-BACK interior (world x≈4.3, z≈12.8). Hero   */}
      {/* piece. Blinking green cursor; scrolls fast when services.taskActive.   */}
      {/* Operator stands in front facing +z toward the kiosk (rotationY = 0),   */}
      {/* pose 'cross'. Scaled ~1.4x.                                            */}
      {/* ===================================================================== */}
      <Interactive
        id="run-script"
        label="Run Script"
        status={taskActive ? 'RUNNING…' : 'Idle — click to run'}
        position={[4.3, 1.5, 12.8]}
        anchor={{ position: [4.3, 0, 11.4], rotationY: 0, pose: 'cross' }}
        ix={ix}
        accent={PALETTE.green}
        ringRadius={1.35}
      >
        {/* floor base */}
        <RoundedBox args={[1.25, 0.14, 0.98]} radius={0.05} smoothness={4} position={[4.3, 0.07, 12.8]} castShadow>
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.6} metalness={0.3} emissiveIntensity={0} />
        </RoundedBox>
        {/* central support column */}
        <mesh position={[4.3, 0.7, 12.85]} castShadow>
          <boxGeometry args={[0.2, 1.26, 0.2]} />
          <meshStandardMaterial color="#0f172a" metalness={0.5} roughness={0.4} emissiveIntensity={0} />
        </mesh>
        {/* tall vertical kiosk screen (portrait), faces -z into room */}
        <group position={[4.3, 1.85, 12.8]}>
          {/* dark bezel */}
          <RoundedBox args={[1.2, 1.68, 0.1]} radius={0.055} smoothness={4} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.45} metalness={0.55} emissiveIntensity={0} />
          </RoundedBox>
          {/* emissive green terminal screen */}
          <mesh position={[0, 0, -0.055]}>
            <planeGeometry args={[1.04, 1.48]} />
            <meshStandardMaterial
              ref={kioskScreenRef}
              color="#03140d"
              emissive={PALETTE.green}
              emissiveIntensity={1.9}
              toneMapped={false}
            />
          </mesh>
          {/* prompt glyph (top-left, steady) */}
          <Text position={[-0.42, 0.64, -0.06]} fontSize={0.11} color={PALETTE.green} anchorX="left" anchorY="middle">
            {'$'}
          </Text>
          {/* scrolling green script lines */}
          <group ref={kioskLinesRef} position={[0, 0, -0.06]}>
            {kioskLines.map((l, i) => (
              <mesh key={`kiosk-${i}`} position={[l.x, 0.7 - i * 0.128, 0]}>
                <planeGeometry args={[l.w, 0.042]} />
                <meshStandardMaterial color={PALETTE.green} emissive={PALETTE.green} emissiveIntensity={2.8} toneMapped={false} />
              </mesh>
            ))}
          </group>
          {/* blinking green cursor block (bottom-left) */}
          <mesh position={[-0.42, -0.58, -0.062]}>
            <planeGeometry args={[0.07, 0.1]} />
            <meshStandardMaterial
              ref={kioskCursorRef}
              color={PALETTE.green}
              emissive={PALETTE.green}
              emissiveIntensity={3.4}
              toneMapped={false}
            />
          </mesh>
        </group>
      </Interactive>

      {/* ===================================================================== */}
      {/* MOOD PIP — small (r ≤ 1.0) functional floor indicator at the kiosk     */}
      {/* base that recolours with the system mood (green idle, red on warning). */}
      {/* References `mood`/`moodColor` without adding any decorative object and  */}
      {/* WITHOUT the old oversized cyan "track" ring.                            */}
      {/* ===================================================================== */}
      <mesh position={[4.3, 0.03, 12.8]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.78, 0.95, 48]} />
        <meshStandardMaterial
          ref={moodPipRef}
          color={moodColor}
          emissive={moodColor}
          emissiveIntensity={moodIsWarning ? 2.4 : 1.8}
          transparent
          opacity={0.55}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
    </group>
  )
}
