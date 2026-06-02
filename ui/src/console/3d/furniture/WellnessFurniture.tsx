// ============================================================================
// JARVIS SPATIAL DASHBOARD — V15 WELLNESS CENTER / "Recharge"
// World rect: x in [7.5, 22], z in [-5.5, 5.5]. Accent purple #a78bfa.
// TALL OUTER WALL = RIGHT wall x=22 (faces -x); all others are 0.9 inner walls.
// Objects render in ABSOLUTE WORLD coords (NOT wrapped in a room-centre group).
// Wall-mounted Sleep Tracker sits on the right outer wall at y≈1.1; every other
// unit is a free-standing floor object (bottom at y=0). Calm purple pulses.
//
// V15 POLISH PASS: geometry scaled ~1.4x for a larger ~3.2-tall Operator and a
// near-top-down camera; free-standing units spread across the room INTERIOR
// (corners + centre) instead of hugging walls. Each moved object carries its
// Interactive position AND its avatar anchor (anchor ~1.4 in front, y=0).
// ============================================================================

import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { RoundedBox, Outlines, Text } from '@react-three/drei'
import * as THREE from 'three'
import { PALETTE } from '../sceneConstants'
import { Interactive } from '../Interactive'
import type { RoomFurnitureProps } from '../dollhouseTypes'

// Right outer wall inner face (x=22, thickness 0.4 → inner face ≈ 21.8). Wall
// items mount just in front, facing -x (toward room interior).
const RIGHT_WALL_X = 21.78

export default function WellnessFurniture({ services, mood, ix }: RoomFurnitureProps) {
  // ---- typed refs ----
  const fitnessRingRef = useRef<THREE.MeshStandardMaterial>(null)
  const fitnessCoreRef = useRef<THREE.MeshStandardMaterial>(null)
  const waterDotMats = useRef<(THREE.MeshStandardMaterial | null)[]>([])
  const waterColumnRef = useRef<THREE.Group>(null)
  const podGlowRef = useRef<THREE.MeshStandardMaterial>(null)
  const podDomeRef = useRef<THREE.Group>(null)
  const sleepBarMats = useRef<(THREE.MeshStandardMaterial | null)[]>([])
  const sleepScoreRef = useRef<THREE.Group>(null)

  const taskActive = services.taskActive
  const processing = services.processing
  const moodSuccess = mood === 'success'

  // Sleep score (deterministic; >80 → green per spec). Bars = deep / light / REM.
  const sleepScore = 82
  const sleepGood = sleepScore > 80
  const sleepBars = useMemo(
    () => [
      { label: 'DEEP', h: 0.62, color: PALETTE.purple },
      { label: 'LIGHT', h: 1.0, color: PALETTE.cyan },
      { label: 'REM', h: 0.46, color: PALETTE.successGreen },
    ],
    [],
  )

  // Water column: 8 stacked dots (index → vertical offset). Variety via index i.
  const waterDots = useMemo(() => [0, 1, 2, 3, 4, 5, 6, 7] as const, [])

  useFrame((state) => {
    const t = state.clock.getElapsedTime()

    // --- FITNESS MAT progress ring: fills cyan→green over a ~14s loop,
    //     flashes green at goal. Faster when a task is active. ---
    const period = taskActive ? 9 : 14
    const progress = (t % period) / period // 0..1
    const atGoal = progress > 0.985
    if (fitnessRingRef.current) {
      const m = fitnessRingRef.current
      // arc swept by scaling Z (thetaLength baked geometrically is costly; we fake
      // fill via emissive intensity ramp + colour blend cyan→green as it nears goal).
      const cyan = new THREE.Color(PALETTE.cyan)
      const green = new THREE.Color(PALETTE.successGreen)
      const blended = cyan.clone().lerp(green, progress)
      if (atGoal) {
        // green goal flash
        const flash = 3.0 + Math.abs(Math.sin(t * 10)) * 3.0
        m.color.set(PALETTE.successGreen)
        m.emissive.set(PALETTE.successGreen)
        m.emissiveIntensity = flash
      } else {
        m.color.copy(blended)
        m.emissive.copy(blended)
        m.emissiveIntensity = 1.9 + progress * 1.4
      }
    }
    // core pip pulses with progress; bright green flash at goal
    if (fitnessCoreRef.current) {
      fitnessCoreRef.current.emissiveIntensity = atGoal
        ? 3.5 + Math.abs(Math.sin(t * 10)) * 2.5
        : 1.9 + Math.sin(t * 2.2) * 0.5
      fitnessCoreRef.current.color.set(atGoal ? PALETTE.successGreen : PALETTE.purple)
      fitnessCoreRef.current.emissive.set(atGoal ? PALETTE.successGreen : PALETTE.purple)
    }

    // --- WATER STATION: 8 cyan dots fill progressively; flashes green when full. ---
    const fillPeriod = 12
    const fillP = (t % fillPeriod) / fillPeriod // 0..1
    const filled = Math.floor(fillP * 9) // 0..8 dots lit
    const full = filled >= 8
    for (let i = 0; i < waterDotMats.current.length; i++) {
      const m = waterDotMats.current[i]
      if (!m) continue
      const isLit = i < filled
      if (full) {
        // all-green full flash
        const flash = 2.6 + Math.abs(Math.sin(t * 9 + i * 0.3)) * 2.6
        m.color.set(PALETTE.successGreen)
        m.emissive.set(PALETTE.successGreen)
        m.emissiveIntensity = flash
      } else if (isLit) {
        m.color.set(PALETTE.cyan)
        m.emissive.set(PALETTE.cyan)
        m.emissiveIntensity = 2.4 + Math.sin(t * 3 + i * 0.5) * 0.4
      } else {
        // unfilled = dim slate, non-glowing
        m.color.set('#1a2536')
        m.emissive.set('#1a2536')
        m.emissiveIntensity = 0.12
      }
    }
    if (waterColumnRef.current) {
      waterColumnRef.current.position.y = 0.68 + Math.sin(t * 1.3) * 0.012
    }

    // --- MEDITATION POD: soft purple glow + slow calming pulse. ---
    if (podGlowRef.current) {
      podGlowRef.current.emissiveIntensity = 1.9 + Math.sin(t * 0.9) * 0.7
    }
    if (podDomeRef.current) {
      const s = 1 + Math.sin(t * 0.9) * 0.012
      podDomeRef.current.scale.set(s, s, s)
    }

    // --- SLEEP TRACKER bars: gentle calming breathe; greener when score is good. ---
    for (let i = 0; i < sleepBarMats.current.length; i++) {
      const m = sleepBarMats.current[i]
      if (!m) continue
      m.emissiveIntensity = 2.0 + Math.sin(t * 1.1 + i * 0.7) * 0.5
    }
    if (sleepScoreRef.current) {
      sleepScoreRef.current.position.y = Math.sin(t * 0.8) * 0.012
    }
  })

  return (
    <group>
      {/* ===================================================================== */}
      {/* 1. FITNESS MAT — flat floor mat + cyan→green circular progress ring   */}
      {/*    Interior TOP-LEFT corner of the room. Operator stands in front(-z). */}
      {/*    Scaled ~1.4x: mat 2.7 x 1.7, ring r=0.66, centre pip r=0.17.        */}
      {/* ===================================================================== */}
      <Interactive
        id="wellness-fitness"
        label="Fitness"
        status={taskActive ? 'Workout active' : 'Daily goal · move ring'}
        position={[10.8, 0.05, -3.1]}
        anchor={{ position: [10.8, 0, -1.7], rotationY: Math.PI, pose: 'reach' }}
        ix={ix}
        accent={PALETTE.purple}
        ringRadius={1.7}
      >
        {/* mat slab (flat, sits on floor) */}
        <mesh position={[10.8, 0.02, -3.1]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <planeGeometry args={[2.7, 1.7]} />
          <meshStandardMaterial color="#13203a" roughness={0.92} metalness={0.04} emissiveIntensity={0} />
        </mesh>
        {/* mat purple edge frame (low emissive) */}
        {(
          [
            { p: [10.8, 0.025, -3.95] as [number, number, number], s: [2.7, 0.07] as [number, number] },
            { p: [10.8, 0.025, -2.25] as [number, number, number], s: [2.7, 0.07] as [number, number] },
            { p: [9.45, 0.025, -3.1] as [number, number, number], s: [0.07, 1.7] as [number, number] },
            { p: [12.15, 0.025, -3.1] as [number, number, number], s: [0.07, 1.7] as [number, number] },
          ]
        ).map((b, i) => (
          <mesh key={`mat-edge-${i}`} position={b.p} rotation={[-Math.PI / 2, 0, 0]}>
            <planeGeometry args={b.s} />
            <meshStandardMaterial color={PALETTE.purple} emissive={PALETTE.purple} emissiveIntensity={1.4} toneMapped={false} />
          </mesh>
        ))}
        {/* circular progress RING lying flat on the mat (cyan→green, flashes at goal) */}
        <mesh position={[10.8, 0.05, -3.1]} rotation={[-Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.66, 0.07, 14, 56]} />
          <meshStandardMaterial
            ref={fitnessRingRef}
            color={PALETTE.cyan}
            emissive={PALETTE.cyan}
            emissiveIntensity={2.1}
            toneMapped={false}
          />
        </mesh>
        {/* faint track under the progress ring */}
        <mesh position={[10.8, 0.04, -3.1]} rotation={[-Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.66, 0.026, 10, 48]} />
          <meshStandardMaterial color="#1f2c47" emissiveIntensity={0} roughness={0.8} />
        </mesh>
        {/* centre pip (pulses with progress, green flash at goal) */}
        <mesh position={[10.8, 0.08, -3.1]}>
          <sphereGeometry args={[0.17, 18, 18]} />
          <meshStandardMaterial
            ref={fitnessCoreRef}
            color={PALETTE.purple}
            emissive={PALETTE.purple}
            emissiveIntensity={2.0}
            toneMapped={false}
          />
        </mesh>
      </Interactive>

      {/* ===================================================================== */}
      {/* 2. WATER STATION — floor dispenser w/ vertical 8-dot fill column      */}
      {/*    Interior BOTTOM-LEFT corner. Operator presses from the front (+z).  */}
      {/*    Scaled ~1.45x footprint; body 0.72 x 1.0 x 0.72 on a 0.18 plinth →   */}
      {/*    droplet-cap top ≈1.29 (≤1.3 free-standing rule). Dots r=0.06.        */}
      {/* ===================================================================== */}
      <Interactive
        id="wellness-water"
        label="Hydration"
        status="Daily intake · 8 cups"
        position={[10.6, 0.65, 3.1]}
        anchor={{ position: [10.6, 0, 1.7], rotationY: 0, pose: 'press' }}
        ix={ix}
        accent={PALETTE.purple}
        ringRadius={1.2}
      >
        {/* base plinth */}
        <mesh position={[10.6, 0.09, 3.1]} castShadow receiveShadow>
          <cylinderGeometry args={[0.6, 0.72, 0.18, 28]} />
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.6} metalness={0.25} emissiveIntensity={0} />
        </mesh>
        {/* main dispenser body (rounded, dark). Bottom flush on plinth top (0.18). */}
        <RoundedBox args={[0.72, 1.0, 0.72]} radius={0.1} smoothness={4} position={[10.6, 0.68, 3.1]} castShadow>
          <meshStandardMaterial color="#0f1a2e" roughness={0.45} metalness={0.4} emissiveIntensity={0}>
          </meshStandardMaterial>
          <Outlines color={PALETTE.purple} thickness={0.025} />
        </RoundedBox>
        {/* clear front fill-tube housing */}
        <RoundedBox args={[0.29, 0.9, 0.08]} radius={0.04} smoothness={4} position={[10.6, 0.68, 2.76]}>
          <meshStandardMaterial color="#0a1424" roughness={0.3} metalness={0.5} transparent opacity={0.55} emissiveIntensity={0} />
        </RoundedBox>
        {/* vertical column of 8 dots (fill progressively, green flash when full) */}
        <group ref={waterColumnRef} position={[10.6, 0.68, 2.72]}>
          {waterDots.map((i) => (
            <mesh key={`water-dot-${i}`} position={[0, -0.36 + i * 0.105, 0]}>
              <sphereGeometry args={[0.06, 14, 14]} />
              <meshStandardMaterial
                ref={(m) => {
                  waterDotMats.current[i] = m
                }}
                color={PALETTE.cyan}
                emissive={PALETTE.cyan}
                emissiveIntensity={2.4}
                toneMapped={false}
              />
            </mesh>
          ))}
        </group>
        {/* spout */}
        <mesh position={[10.6, 0.34, 2.84]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.05, 0.05, 0.23, 12]} />
          <meshStandardMaterial color="#334155" roughness={0.4} metalness={0.6} emissiveIntensity={0} />
        </mesh>
        {/* top droplet cap (purple accent) — sits on body top (1.18); top ≈1.29 */}
        <mesh position={[10.6, 1.15, 3.1]}>
          <sphereGeometry args={[0.14, 16, 16]} />
          <meshStandardMaterial color={PALETTE.purple} emissive={PALETTE.purple} emissiveIntensity={1.8} toneMapped={false} />
        </mesh>
      </Interactive>

      {/* ===================================================================== */}
      {/* 3. MEDITATION POD — dome/seat in the ROOM CENTRE, soft purple pulse   */}
      {/*    Hero piece pulled into the interior. Operator sits inside (faces +x */}
      {/*    from the -x side). Scaled ~1.45x: seat 1.45 wide, dome r=0.95.      */}
      {/* ===================================================================== */}
      <Interactive
        id="wellness-meditate"
        label="Meditate"
        status="Recharge · breathe"
        position={[16.0, 0.45, 0.6]}
        anchor={{ position: [14.6, 0, 0.6], rotationY: Math.PI / 2, pose: 'sit' }}
        ix={ix}
        accent={PALETTE.purple}
        ringRadius={1.55}
      >
        <group ref={podDomeRef} position={[16.0, 0, 0.6]}>
          {/* seat cushion base (rounded, bottom flush on floor at y=0) */}
          <RoundedBox args={[1.45, 0.4, 1.45]} radius={0.16} smoothness={4} position={[0, 0.2, 0]} castShadow receiveShadow>
            <meshStandardMaterial color={PALETTE.slateDark} roughness={0.6} metalness={0.15} emissiveIntensity={0} />
          </RoundedBox>
          {/* dome shell (open-front half sphere) */}
          <mesh position={[0, 0.48, 0]} castShadow>
            <sphereGeometry args={[0.95, 28, 20, 0, Math.PI * 2, 0, Math.PI / 2]} />
            <meshStandardMaterial color="#101a2e" roughness={0.5} metalness={0.3} side={THREE.DoubleSide} emissiveIntensity={0} />
          </mesh>
          {/* inner soft purple glow disc (the calming light source) */}
          <mesh position={[0, 0.48, 0]}>
            <sphereGeometry args={[0.75, 24, 18]} />
            <meshStandardMaterial
              ref={podGlowRef}
              color={PALETTE.purple}
              emissive={PALETTE.purple}
              emissiveIntensity={2.0}
              transparent
              opacity={0.7}
              toneMapped={false}
            />
          </mesh>
          {/* purple rim ring around the dome opening */}
          <mesh position={[0, 0.49, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.9, 0.045, 12, 48]} />
            <meshStandardMaterial color={PALETTE.purple} emissive={PALETTE.purple} emissiveIntensity={2.2} toneMapped={false} />
          </mesh>
        </group>
      </Interactive>

      {/* ===================================================================== */}
      {/* 4. SLEEP TRACKER DISPLAY — vertical screen on the RIGHT OUTER wall     */}
      {/*    x≈21.78, y≈1.1, faces -x. Bar chart (deep/light/REM) + score Text.   */}
      {/*    Operator stands in front (faces +x → rotationY = Math.PI/2), points. */}
      {/*    Bezel 1.0 x 1.18 (≤1.2 wall-item rule); centred y=1.1 → top 1.69,    */}
      {/*    flush under the 1.7 tall outer wall (no poke-through, no float).      */}
      {/* ===================================================================== */}
      <Interactive
        id="wellness-sleep"
        label="Sleep"
        status={`Score ${sleepScore} · ${sleepGood ? 'great' : 'fair'}`}
        position={[RIGHT_WALL_X - 0.08, 1.1, -2.4]}
        anchor={{ position: [20.3, 0, -2.4], rotationY: Math.PI / 2, pose: 'point' }}
        ix={ix}
        accent={PALETTE.purple}
        ringRadius={1.2}
        tooltipHeight={1.2}
      >
        {/* panel group mounted on right wall, screen faces -x (room interior).
            Bezel 1.18 tall, centred y=1.1 → top 1.69, flush under the 1.7 outer
            wall (wall-item ≤1.2 rule); internals rescaled to fit the shorter panel. */}
        <group position={[RIGHT_WALL_X, 1.1, -2.4]} rotation={[0, -Math.PI / 2, 0]}>
          {/* bezel (vertical/portrait screen) */}
          <RoundedBox args={[1.0, 1.18, 0.1]} radius={0.06} smoothness={4} position={[0, 0, 0]} castShadow>
            <meshStandardMaterial color="#0b1220" roughness={0.45} metalness={0.5} emissiveIntensity={0} />
          </RoundedBox>
          {/* dark glowing screen face (toward room → local +z) */}
          <mesh position={[0, 0, 0.055]}>
            <planeGeometry args={[0.88, 1.06]} />
            <meshStandardMaterial color="#0a1326" emissive={PALETTE.purple} emissiveIntensity={0.5} toneMapped={false} />
          </mesh>

          {/* header label */}
          <Text position={[0, 0.46, 0.07]} fontSize={0.11} color={PALETTE.purple} anchorX="center" anchorY="middle">
            SLEEP
          </Text>

          {/* bar chart: deep / light / REM (bases aligned at y≈-0.16) */}
          {sleepBars.map((b, i) => {
            const baseY = -0.16
            const x = -0.26 + i * 0.26
            return (
              <group key={`sleep-bar-${i}`}>
                {/* faint track */}
                <mesh position={[x, baseY + 0.4, 0.07]}>
                  <boxGeometry args={[0.13, 0.8, 0.02]} />
                  <meshStandardMaterial color="#16223a" emissiveIntensity={0} roughness={0.8} />
                </mesh>
                {/* filled bar */}
                <mesh position={[x, baseY + (b.h * 0.8) / 2, 0.078]}>
                  <boxGeometry args={[0.13, b.h * 0.8, 0.026]} />
                  <meshStandardMaterial
                    ref={(m) => {
                      sleepBarMats.current[i] = m
                    }}
                    color={b.color}
                    emissive={b.color}
                    emissiveIntensity={2.0}
                    toneMapped={false}
                  />
                </mesh>
                {/* bar label */}
                <Text position={[x, baseY - 0.1, 0.07]} fontSize={0.055} color="#94a3b8" anchorX="center" anchorY="middle">
                  {b.label}
                </Text>
              </group>
            )
          })}

          {/* big score number (green if >80) */}
          <group ref={sleepScoreRef} position={[0, -0.42, 0.08]}>
            <Text
              fontSize={0.32}
              color={sleepGood ? PALETTE.successGreen : PALETTE.amber}
              anchorX="center"
              anchorY="middle"
              outlineWidth={0.004}
              outlineColor={sleepGood ? PALETTE.successGreen : PALETTE.amber}
            >
              {String(sleepScore)}
            </Text>
            <Text position={[0, -0.21, 0]} fontSize={0.06} color="#94a3b8" anchorX="center" anchorY="middle">
              SLEEP SCORE
            </Text>
          </group>
        </group>
      </Interactive>

      {/* ===================================================================== */}
      {/* ROOM AMBIENCE — gentle purple recharge light (non-interactive).        */}
      {/* Slightly brighter while the system is processing/recharging.           */}
      {/* ===================================================================== */}
      <pointLight
        position={[14.75, 1.5, 0]}
        color={PALETTE.purple}
        intensity={processing || moodSuccess ? 1.0 : 0.6}
        distance={12}
        decay={2}
      />
    </group>
  )
}
