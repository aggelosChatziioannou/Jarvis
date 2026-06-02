// ============================================================================
// JARVIS SPATIAL DASHBOARD — V15 OFFICE / COMMAND CENTER FURNITURE
// ----------------------------------------------------------------------------
// Room rect: x ∈ [-22, -7.5], z ∈ [-5.5, 16]. Accent CYAN.
// TALL OUTER WALLS: LEFT wall x=-22 (faces +x), BOTTOM wall z=16 (faces -z).
// Inner face of the LEFT outer wall sits ~0.2 inside its line (WT=0.4) → LEFT
// inner face ≈ -21.6. Wall-mounted items (calendar/pinboard/task board) hug just
// inside the LEFT wall; free-standing pieces (desk/chair/cabinet) are distributed
// across the room interior so the large floor reads full under a near-top-down cam.
//
// Renders in ABSOLUTE WORLD coordinates (NOT wrapped in a room-centre group).
// Every object is a live UI element wrapped in <Interactive>; NO decoration.
// All animation time comes from state.clock; every ref is guarded + typed.
// ============================================================================

import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { RoundedBox, Outlines, Text } from '@react-three/drei'
import * as THREE from 'three'
import { PALETTE } from '../sceneConstants'
import { Interactive } from '../Interactive'
import type { RoomFurnitureProps } from '../dollhouseTypes'

// ---- WORLD anchors for the two tall outer walls ----
// LEFT outer wall line is x=-22; its inner face sits ~0.2 inside (WT=0.4).
const LEFT_FACE_X = -21.55 // just inside the inner face (mount plane for wall items)

// Desk is now FREE-STANDING in the room interior (no longer pinned to the wall),
// facing the room so its top runs along z. Operator works from the +x (interior)
// side, so laptop/monitor face +x. Scaled ~1.4x for the larger ~3.2 Operator.
const DESK_X = -17.5
const DESK_TOP_Y = 0.86

export default function OfficeFurniture({ services, mood, ix }: RoomFurnitureProps) {
  // ---- typed refs (all guarded in useFrame) ----
  const laptopScreenRef = useRef<THREE.MeshStandardMaterial>(null)
  const envelopeRef = useRef<THREE.Group>(null)
  const globeRef = useRef<THREE.Group>(null)
  const globeMatRef = useRef<THREE.MeshStandardMaterial>(null)
  const monitorScreenRef = useRef<THREE.MeshStandardMaterial>(null)
  const calendarRingRef = useRef<THREE.MeshStandardMaterial>(null)
  const calendarGroupRef = useRef<THREE.Group>(null)
  const inProgressRefs = useRef<Array<THREE.MeshStandardMaterial | null>>([])
  const cabinetDrawerRef = useRef<THREE.MeshStandardMaterial>(null)

  const hasUnread = services.gmailUnread > 0
  const calAlert = services.calendarAlert
  const taskActive = services.taskActive
  const moodIsWarning = mood === 'warning'

  useFrame((state) => {
    const t = state.clock.getElapsedTime()

    // (1a) LAPTOP screen — blink white ~every 2s while unread, else steady glow.
    if (laptopScreenRef.current) {
      laptopScreenRef.current.emissiveIntensity = hasUnread
        ? Math.sin(t * Math.PI) > 0
          ? 3.4
          : 0.6
        : 2.6
    }
    // Floating envelope above laptop — only visible while unread; floats + bobs.
    if (envelopeRef.current) {
      envelopeRef.current.visible = hasUnread
      envelopeRef.current.position.y = DESK_TOP_Y + 0.86 + Math.sin(t * 2.4) * 0.1
      envelopeRef.current.rotation.y = Math.sin(t * 0.9) * 0.28
    }

    // (1b) SECOND MONITOR — cyan globe spins while a task is active; screen breathe.
    if (monitorScreenRef.current) {
      monitorScreenRef.current.emissiveIntensity = 1.9 + Math.sin(t * 1.4) * 0.3
    }
    if (globeRef.current && taskActive) {
      globeRef.current.rotation.y = t * 1.6
    }
    if (globeMatRef.current) {
      globeMatRef.current.emissiveIntensity = taskActive
        ? 4.2 + Math.sin(t * 4) * 0.6
        : 2.2
    }

    // (3) WALL CALENDAR — amber pulse + countdown while calendarAlert, else cyan.
    if (calendarRingRef.current) {
      if (calAlert) {
        calendarRingRef.current.emissiveIntensity = 2.6 + Math.sin(t * 5) * 1.4
        calendarRingRef.current.color.set(PALETTE.amber)
        calendarRingRef.current.emissive.set(PALETTE.amber)
      } else {
        calendarRingRef.current.emissiveIntensity = 2
        calendarRingRef.current.color.set(PALETTE.cyan)
        calendarRingRef.current.emissive.set(PALETTE.cyan)
      }
    }
    if (calendarGroupRef.current && calAlert) {
      calendarGroupRef.current.scale.setScalar(1 + Math.sin(t * 5) * 0.02)
    }

    // (5) TASK MANAGER — In-Progress (amber) cards pulse, offset by index.
    inProgressRefs.current.forEach((mat, i) => {
      if (mat) mat.emissiveIntensity = 2.4 + Math.sin(t * 3 + i * 1.3) * 1.0
    })

    // (6) FILE CABINET — top drawer glows while a task is active, else dim.
    if (cabinetDrawerRef.current) {
      cabinetDrawerRef.current.emissiveIntensity = taskActive
        ? 3.4 + Math.sin(t * 4) * 0.8
        : 0.4
    }
  })

  return (
    <group>
      {/* ================================================================== */}
      {/* 1. DESK (free-standing, room interior) + LAPTOP (Gmail) + MONITOR (Browser) */}
      {/* ================================================================== */}
      {/* Desk carcass — free-standing in the interior, top runs along z, operator on +x. Non-clickable. */}
      <group position={[DESK_X, 0, 1.0]}>
        {/* desk top */}
        <RoundedBox args={[1.4, 0.14, 4.4]} radius={0.05} smoothness={4} position={[0, DESK_TOP_Y, 0]} castShadow>
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.55} metalness={0.25} emissiveIntensity={0} />
        </RoundedBox>
        {/* four legs */}
        {(
          [
            [-0.56, 0.43, -2.0],
            [0.56, 0.43, -2.0],
            [-0.56, 0.43, 2.0],
            [0.56, 0.43, 2.0],
          ] as [number, number, number][]
        ).map((p, i) => (
          <mesh key={`leg-${i}`} position={p} castShadow>
            <boxGeometry args={[0.1, 0.86, 0.1]} />
            <meshStandardMaterial color="#0f172a" roughness={0.6} metalness={0.3} emissiveIntensity={0} />
          </mesh>
        ))}
      </group>

      {/* ----- LAPTOP (Gmail) — clickable, pose 'type' ----- */}
      <Interactive
        id="office-laptop"
        label="Gmail"
        status={hasUnread ? `${services.gmailUnread} unread` : 'Inbox clear'}
        position={[DESK_X, DESK_TOP_Y + 0.35, 0.5]}
        anchor={{ position: [DESK_X + 1.4, 0, 0.5], rotationY: -Math.PI / 2, pose: 'type' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.1}
      >
        {/* base + tilted screen, opening toward +x (the operator) */}
        <group position={[DESK_X, DESK_TOP_Y + 0.07, 0.5]} rotation={[0, Math.PI / 2, 0]}>
          {/* keyboard base */}
          <RoundedBox args={[0.88, 0.06, 0.62]} radius={0.025} smoothness={4} position={[0, 0, 0.11]} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.4} metalness={0.6} emissiveIntensity={0} />
          </RoundedBox>
          {/* screen lid (tilted back) */}
          <group position={[0, 0, -0.2]} rotation={[-Math.PI / 2.55, 0, 0]}>
            <RoundedBox args={[0.88, 0.6, 0.035]} radius={0.02} smoothness={4} position={[0, 0.3, 0]} castShadow>
              <meshStandardMaterial color="#0b1220" roughness={0.4} metalness={0.6} emissiveIntensity={0} />
            </RoundedBox>
            {/* glowing white screen panel */}
            <mesh position={[0, 0.3, 0.022]}>
              <planeGeometry args={[0.76, 0.48]} />
              <meshStandardMaterial
                ref={laptopScreenRef}
                color={PALETTE.whiteLight}
                emissive={PALETTE.whiteLight}
                emissiveIntensity={2.6}
                toneMapped={false}
              />
            </mesh>
          </group>
        </group>

        {/* floating emissive envelope above the laptop (unread only) */}
        <group ref={envelopeRef} position={[DESK_X, DESK_TOP_Y + 0.86, 0.5]}>
          <RoundedBox args={[0.37, 0.24, 0.03]} radius={0.015} smoothness={4}>
            <meshStandardMaterial
              color={PALETTE.whiteLight}
              emissive={PALETTE.whiteLight}
              emissiveIntensity={3.2}
              toneMapped={false}
            />
          </RoundedBox>
          {/* flap */}
          <mesh position={[0, 0.007, 0.017]} rotation={[0, 0, Math.PI]}>
            <coneGeometry args={[0.17, 0.11, 3]} />
            <meshStandardMaterial color="#cbd5e1" emissive={PALETTE.whiteLight} emissiveIntensity={1.6} toneMapped={false} />
          </mesh>
        </group>
      </Interactive>

      {/* ----- SECOND MONITOR (Browser) — vertical screen, clickable, pose 'reach' ----- */}
      <Interactive
        id="office-monitor"
        label="Browser"
        status={taskActive ? 'Task running' : 'Idle'}
        position={[DESK_X, DESK_TOP_Y + 0.82, -1.1]}
        anchor={{ position: [DESK_X + 1.4, 0, -1.1], rotationY: -Math.PI / 2, pose: 'reach' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.1}
      >
        {/* monitor sits on desk; screen face points +x toward the operator */}
        <group position={[DESK_X, DESK_TOP_Y, -1.1]} rotation={[0, Math.PI / 2, 0]}>
          {/* stand */}
          <mesh position={[0, 0.1, 0]} castShadow>
            <cylinderGeometry args={[0.06, 0.1, 0.2, 12]} />
            <meshStandardMaterial color="#0f172a" metalness={0.5} roughness={0.4} emissiveIntensity={0} />
          </mesh>
          {/* vertical bezel */}
          <RoundedBox args={[0.7, 1.04, 0.07]} radius={0.035} smoothness={4} position={[0, 0.73, 0]} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.45} metalness={0.55} emissiveIntensity={0} />
          </RoundedBox>
          {/* emissive screen surface (faces +z local → +x world) */}
          <mesh position={[0, 0.73, 0.04]}>
            <planeGeometry args={[0.59, 0.92]} />
            <meshStandardMaterial
              ref={monitorScreenRef}
              color="#0e2a33"
              emissive={PALETTE.cyan}
              emissiveIntensity={1.9}
              toneMapped={false}
            />
          </mesh>
          {/* spinning cyan wireframe globe icon on the screen */}
          <group ref={globeRef} position={[0, 0.73, 0.085]}>
            <mesh>
              <sphereGeometry args={[0.18, 16, 12]} />
              <meshStandardMaterial
                ref={globeMatRef}
                color={PALETTE.cyan}
                emissive={PALETTE.cyan}
                emissiveIntensity={4}
                wireframe
                toneMapped={false}
              />
            </mesh>
          </group>
        </group>
      </Interactive>

      {/* ================================================================== */}
      {/* 2. OFFICE CHAIR (behind the desk, +x side) — NON-interactive */}
      {/* ================================================================== */}
      <group position={[DESK_X + 1.4, 0, 0.6]}>
        {/* seat */}
        <RoundedBox args={[1.08, 0.2, 1.08]} radius={0.08} smoothness={4} position={[0, 0.7, 0]} castShadow>
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.5} metalness={0.2} emissiveIntensity={0} />
          <Outlines color={PALETTE.cyan} thickness={0.04} />
        </RoundedBox>
        {/* backrest (toward +x, away from desk) */}
        <RoundedBox args={[0.16, 1.1, 1.08]} radius={0.08} smoothness={4} position={[0.5, 1.28, 0]} castShadow>
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.5} metalness={0.2} emissiveIntensity={0} />
          <Outlines color={PALETTE.cyan} thickness={0.04} />
        </RoundedBox>
        {/* center post */}
        <mesh position={[0, 0.35, 0]} castShadow>
          <cylinderGeometry args={[0.07, 0.1, 0.7, 12]} />
          <meshStandardMaterial color="#0f172a" metalness={0.6} roughness={0.35} emissiveIntensity={0} />
        </mesh>
        {/* 5-star base */}
        <mesh position={[0, 0.06, 0]} castShadow>
          <cylinderGeometry args={[0.48, 0.48, 0.09, 5]} />
          <meshStandardMaterial color="#0f172a" metalness={0.6} roughness={0.35} emissiveIntensity={0} />
        </mesh>
      </group>

      {/* ================================================================== */}
      {/* 3. WALL CALENDAR (LEFT outer wall, faces +x) — clickable, pose 'point' */}
      {/* ================================================================== */}
      <Interactive
        id="office-calendar"
        label="Calendar"
        status={calAlert ? 'Meeting in 1h' : 'No alerts'}
        position={[LEFT_FACE_X, 1.1, -3.2]}
        anchor={{ position: [LEFT_FACE_X + 1.4, 0, -3.2], rotationY: -Math.PI / 2, pose: 'point' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.2}
      >
        {/* disc lies in the wall plane (flat face → +x) */}
        <group ref={calendarGroupRef} position={[LEFT_FACE_X, 1.1, -3.2]} rotation={[0, 0, 0]}>
          {/* dark backing disc (axis along x so face points +x) */}
          <mesh rotation={[0, 0, Math.PI / 2]}>
            <cylinderGeometry args={[0.76, 0.76, 0.07, 40]} />
            <meshStandardMaterial color="#0b1220" roughness={0.5} metalness={0.4} emissiveIntensity={0} />
          </mesh>
          {/* glowing ring on the disc face (hole along +x) */}
          <mesh position={[0.045, 0, 0]} rotation={[0, Math.PI / 2, 0]}>
            <torusGeometry args={[0.68, 0.055, 12, 48]} />
            <meshStandardMaterial
              ref={calendarRingRef}
              color={PALETTE.cyan}
              emissive={PALETTE.cyan}
              emissiveIntensity={2}
              toneMapped={false}
            />
          </mesh>
          {/* date / countdown text, facing +x into the room */}
          <Text
            position={[0.085, 0.11, 0]}
            rotation={[0, Math.PI / 2, 0]}
            fontSize={0.42}
            color={calAlert ? PALETTE.amber : PALETTE.whiteLight}
            anchorX="center"
            anchorY="middle"
          >
            {calAlert ? '1h' : '31'}
          </Text>
          <Text
            position={[0.085, -0.28, 0]}
            rotation={[0, Math.PI / 2, 0]}
            fontSize={0.15}
            color={calAlert ? PALETTE.amber : PALETTE.cyan}
            anchorX="center"
            anchorY="middle"
          >
            {calAlert ? 'MEETING' : 'MAY'}
          </Text>
        </group>
      </Interactive>

      {/* ================================================================== */}
      {/* 4. PINBOARD (Notes) — LEFT outer wall, faces +x. Clickable, pose 'reach' */}
      {/* ================================================================== */}
      <Interactive
        id="office-pinboard"
        label="Notes"
        status="3 pinned"
        position={[LEFT_FACE_X, 1.1, -1.0]}
        anchor={{ position: [LEFT_FACE_X + 1.4, 0, -1.0], rotationY: -Math.PI / 2, pose: 'reach' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.2}
      >
        <group position={[LEFT_FACE_X, 1.1, -1.0]} rotation={[0, Math.PI / 2, 0]}>
          {/* panel */}
          <RoundedBox args={[1.26, 1.1, 0.07]} radius={0.04} smoothness={4} castShadow>
            <meshStandardMaterial color="#33415580" roughness={0.85} metalness={0.05} emissiveIntensity={0} />
          </RoundedBox>
          {/* frame */}
          <mesh position={[0, 0, -0.015]}>
            <boxGeometry args={[1.36, 1.19, 0.055]} />
            <meshStandardMaterial color="#0f172a" roughness={0.7} metalness={0.2} emissiveIntensity={0} />
          </mesh>
          {/* 3 sticky notes — yellow / pink / blue */}
          {(
            [
              { color: '#fde047', pos: [-0.31, 0.25, 0.055] as [number, number, number], rot: 0.1 },
              { color: '#f9a8d4', pos: [0.28, 0.14, 0.055] as [number, number, number], rot: -0.08 },
              { color: PALETTE.controlBlue, pos: [-0.03, -0.28, 0.055] as [number, number, number], rot: 0.05 },
            ] as const
          ).map((s, i) => (
            <RoundedBox
              key={`sticky-${i}`}
              args={[0.36, 0.36, 0.03]}
              radius={0.015}
              smoothness={4}
              position={s.pos}
              rotation={[0, 0, s.rot]}
            >
              <meshStandardMaterial color={s.color} emissive={s.color} emissiveIntensity={0.9} toneMapped={false} />
            </RoundedBox>
          ))}
        </group>
      </Interactive>

      {/* ================================================================== */}
      {/* 5. TASK MANAGER BOARD — LEFT outer wall, faces +x. Clickable, pose 'point' */}
      {/* ================================================================== */}
      <Interactive
        id="office-tasks"
        label="Task Manager"
        status={taskActive ? 'In progress' : 'Idle'}
        position={[LEFT_FACE_X, 1.1, 1.4]}
        anchor={{ position: [LEFT_FACE_X + 1.4, 0, 1.4], rotationY: -Math.PI / 2, pose: 'point' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.25}
      >
        <group position={[LEFT_FACE_X, 1.1, 1.4]} rotation={[0, Math.PI / 2, 0]}>
          {/* board backing (vertical) */}
          <RoundedBox args={[1.7, 1.2, 0.07]} radius={0.04} smoothness={4} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.6} metalness={0.25} emissiveIntensity={0} />
          </RoundedBox>
          {/* 3 columns: ToDo (cyan dim) / InProgress (amber pulse) / Done (dim green) */}
          {(
            [
              { x: -0.56, color: PALETTE.cyan, label: 'TODO', cards: 2, kind: 'todo' },
              { x: 0.0, color: PALETTE.amber, label: 'WIP', cards: 2, kind: 'wip' },
              { x: 0.56, color: PALETTE.successGreen, label: 'DONE', cards: 2, kind: 'done' },
            ] as const
          ).map((col, c) => (
            <group key={`col-${c}`} position={[col.x, 0, 0.055]}>
              {/* column header label */}
              <Text position={[0, 0.5, 0]} fontSize={0.1} color={col.color} anchorX="center" anchorY="middle">
                {col.label}
              </Text>
              {/* cards */}
              {Array.from({ length: col.cards }).map((_, k) => {
                const isWip = col.kind === 'wip'
                const isDone = col.kind === 'done'
                return (
                  <mesh key={`card-${c}-${k}`} position={[0, 0.25 - k * 0.31, 0.014]}>
                    <boxGeometry args={[0.42, 0.22, 0.03]} />
                    <meshStandardMaterial
                      ref={
                        isWip
                          ? (m) => {
                              inProgressRefs.current[c * 2 + k] = m
                            }
                          : undefined
                      }
                      color={col.color}
                      emissive={col.color}
                      emissiveIntensity={isWip ? 2.4 : isDone ? 0.6 : 1.4}
                      toneMapped={false}
                    />
                  </mesh>
                )
              })}
            </group>
          ))}
        </group>
      </Interactive>

      {/* ================================================================== */}
      {/* 6. FILE CABINET — free-standing in the BOTTOM interior, faces -z. Pose 'press' */}
      {/* ================================================================== */}
      <Interactive
        id="office-cabinet"
        label="File Cabinet"
        status={taskActive ? 'Active drawer' : 'Archived'}
        position={[-13.0, 0.65, 12.6]}
        anchor={{ position: [-13.0, 0, 11.0], rotationY: 0, pose: 'press' }}
        ix={ix}
        accent={PALETTE.cyan}
        ringRadius={1.15}
      >
        {/* cabinet body — free-standing floor unit, faces -z into the room */}
        <group position={[-13.0, 0, 12.6]}>
          {/* carcass (bottom at y=0) — height capped ~1.3 for free-standing furniture */}
          <RoundedBox args={[1.26, 1.3, 0.78]} radius={0.05} smoothness={4} position={[0, 0.65, 0]} castShadow>
            <meshStandardMaterial color={PALETTE.slateDark} roughness={0.6} metalness={0.25} emissiveIntensity={0} />
          </RoundedBox>
          {/* 3 drawers (front face toward -z) + cyan LED strip on each */}
          {([0, 1, 2] as const).map((d) => {
            const cy = 0.3 + d * 0.39 // drawer centres bottom→top
            const isTop = d === 2 // the "active" drawer
            return (
              <group key={`drawer-${d}`} position={[0, cy, -0.4]}>
                {/* drawer front */}
                <RoundedBox args={[1.12, 0.34, 0.06]} radius={0.03} smoothness={4} castShadow>
                  <meshStandardMaterial color="#0f172a" roughness={0.55} metalness={0.3} emissiveIntensity={0} />
                </RoundedBox>
                {/* handle */}
                <mesh position={[0, 0, 0.05]}>
                  <boxGeometry args={[0.48, 0.06, 0.04]} />
                  <meshStandardMaterial color="#0b1220" roughness={0.4} metalness={0.5} emissiveIntensity={0} />
                </mesh>
                {/* cyan LED strip — top drawer is the task-active glow target */}
                <mesh position={[0.42, 0.11, 0.05]}>
                  <boxGeometry args={[0.14, 0.04, 0.03]} />
                  {isTop ? (
                    <meshStandardMaterial
                      ref={cabinetDrawerRef}
                      color={PALETTE.cyan}
                      emissive={PALETTE.cyan}
                      emissiveIntensity={0.4}
                      toneMapped={false}
                    />
                  ) : (
                    <meshStandardMaterial
                      color={PALETTE.cyan}
                      emissive={PALETTE.cyan}
                      emissiveIntensity={1.6}
                      toneMapped={false}
                    />
                  )}
                </mesh>
              </group>
            )
          })}
          {/* top accent recolors with a warning mood so the unit reads system state */}
          <mesh position={[0, 1.32, 0]}>
            <boxGeometry args={[1.28, 0.04, 0.8]} />
            <meshStandardMaterial
              color={moodIsWarning ? PALETTE.warningRed : PALETTE.cyan}
              emissive={moodIsWarning ? PALETTE.warningRed : PALETTE.cyan}
              emissiveIntensity={1.8}
              toneMapped={false}
            />
          </mesh>
        </group>
      </Interactive>
    </group>
  )
}
