// ============================================================================
// JARVIS SPATIAL DASHBOARD — V15 LIVING ROOM / ENTERTAINMENT HUB
// ----------------------------------------------------------------------------
// Renders in ABSOLUTE WORLD coordinates (NOT wrapped in a room-centre group).
// World rect: x ∈ [-7.5, 22], z ∈ [-16, -5.5]  (width ≈29.5, depth ≈10.5).
// Accent amber #fbbf24. Room centre ≈ (7.25, -10.75).
//
// TALL OUTER WALLS (height 1.7) — the only valid mounts for wall objects:
//   • TOP wall   z = -16  (inner face ≈ -15.8, faces +z into the room)
//   • RIGHT wall x =  22  (inner face ≈  21.8, faces -x into the room)
//
// V15 POLISH PASS:
//   • Geometry scaled ~1.3–1.5× for the larger ~3.2-tall Operator.
//   • Free-standing pieces (L-SOFA, now-playing table) pulled INTO the room
//     interior — no longer hugging the walls. Wall-mounted screen + media
//     console stay on the TOP outer wall, centred y 1.0–1.2.
//   • The amber sofa is now a clear chunky L-SHAPED SOFA: seat base + raised
//     BACKREST + ARMRESTS + an L return, opening toward the room interior.
//
// FUNCTIONAL OBJECTS (every piece is a live UI element — no decoration):
//   1. L-SHAPED SOFA — chunky amber RoundedBox L, free-standing in the room,
//      back toward the TOP/RIGHT, opening to the interior. Click "Relax" (sit).
//   2. MEDIA CONSOLE (Spotify) on the TOP wall: (a) VINYL PLAYER (spins while
//      services.spotify) → "Play / Pause" (press); (b) SOUND-WAVE VISUALIZER
//      (3 cyan bars, scale.y dances while spotify); (c) HEADPHONES STAND →
//      "Focus Mode" (reach).
//   3. ENTERTAINMENT WALL — 16:9 screen on the TOP wall above the console;
//      musical-note icon glows when spotify else dim. Click (point).
//   4. SIDE TABLE + NOW-PLAYING HOLOGRAM — floating translucent cyan panel with
//      the live track name ("Midnight City" / "SILENCE"), bobbing. Clickable.
//
// Animation: all time from state.clock; every ref guarded & typed; no module
// randomness (index i drives variety). Bloom is global (threshold ~0.8): glowing
// parts use emissive + emissiveIntensity ≥ 1.8 + toneMapped={false}; structural
// materials are non-emissive (emissiveIntensity 0).
// ============================================================================
import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { RoundedBox, Text } from '@react-three/drei'
import * as THREE from 'three'
import { PALETTE } from '../sceneConstants'
import { Interactive } from '../Interactive'
import type { RoomFurnitureProps } from '../dollhouseTypes'

// Inner face of the TOP tall outer wall (wall thickness 0.4 ⇒ 0.2 inset).
// (The RIGHT wall is still a valid mount, but no current Living object hugs it —
// the sofa is now free-standing in the room interior per the V15 polish pass.)
const TOP_WALL_Z = -16 + 0.2 // ≈ -15.8  (faces +z)

// Softer amber tones for cushions (matte, structural — non-emissive base).
const AMBER_SOFT = '#f59e0b'
const AMBER_SEAT = '#fcd34d'

// ---- L-SOFA placement (free-standing in the room interior) ----
// Anchored around its inner corner; the L wraps the +x/-z (TOP/RIGHT) side and
// opens toward the room centre (-x / +z). Pulled clear of the walls.
const SOFA_CX = 16.6 // long run sits around here in x
const SOFA_CZ = -11.4 // and here in z (well inside z[-16,-5.5])
const SEAT_TOP_Y = 0.92 // seat-cushion top height (chunky, suits ~3.2 Operator)

export default function LivingFurniture({ services, mood, ix }: RoomFurnitureProps) {
  // ---- typed refs (all guarded in useFrame) ----
  const vinylRef = useRef<THREE.Mesh>(null)
  const vinylCenterRef = useRef<THREE.MeshStandardMaterial>(null)
  const barsRef = useRef<THREE.Group>(null)
  const consoleAccentRef = useRef<THREE.MeshStandardMaterial>(null)
  const sofaGlowRef = useRef<THREE.MeshStandardMaterial>(null)
  const headphoneCupRefs = useRef<Array<THREE.MeshStandardMaterial | null>>([])
  const screenMatRef = useRef<THREE.MeshStandardMaterial>(null)
  const noteMatRef = useRef<THREE.MeshStandardMaterial>(null)
  const tvBarsRef = useRef<THREE.Group>(null)
  const holoRef = useRef<THREE.Group>(null)
  const holoPanelRef = useRef<THREE.MeshStandardMaterial>(null)

  const playing = services.spotify
  // System-mood recolour: amber room turns hot-red when the system warns.
  const moodIsWarning = mood === 'warning'
  const sofaGlowColor = moodIsWarning ? PALETTE.warningRed : PALETTE.amber

  useFrame((state) => {
    const t = state.clock.getElapsedTime()

    // 1. Sofa under-glow — slow amber breathe (hot-red on warning).
    if (sofaGlowRef.current) {
      sofaGlowRef.current.emissiveIntensity = 1.9 + Math.sin(t * 1.3) * 0.4
      sofaGlowRef.current.color.set(sofaGlowColor)
      sofaGlowRef.current.emissive.set(sofaGlowColor)
    }

    // 2a. Vinyl record spins only while Spotify is playing; centre dot breathes.
    if (vinylRef.current && playing) {
      vinylRef.current.rotation.z = t * Math.PI // ~0.5 rev/s
    }
    if (vinylCenterRef.current) {
      vinylCenterRef.current.emissiveIntensity = playing ? 4 + Math.sin(t * 4) * 1 : 1.8
    }

    // 2b. Sound-wave visualizer — 3 bars bounce scale.y while playing, settle flat when idle.
    if (barsRef.current) {
      barsRef.current.children.forEach((child, i) => {
        const bar = child as THREE.Mesh
        const target = playing ? 1 + (Math.sin(t * 3 + i) * 0.5 + 0.5) * 1.6 : 0.22
        bar.scale.y += (target - bar.scale.y) * 0.18
        bar.position.y = bar.scale.y * 0.34 // keep base anchored, grow upward
      })
    }

    // Media-console amber accent strip pulses while playing, dark when idle.
    if (consoleAccentRef.current) {
      consoleAccentRef.current.emissiveIntensity = playing ? 2.0 + Math.sin(t * 4) * 1.4 : 0.0
    }

    // 2c. Headphone ear-cups gently pulse cyan (offset per cup).
    headphoneCupRefs.current.forEach((mat, i) => {
      if (mat) mat.emissiveIntensity = 2.6 + Math.sin(t * 2.2 + i * Math.PI) * 0.6
    })

    // 3. Entertainment wall: screen always idles a faint wash; the musical note
    // glows bright while spotify, dims when silent. Equalizer bars only dance
    // while playing.
    if (screenMatRef.current) {
      screenMatRef.current.emissiveIntensity = 1.4 + Math.sin(t * 0.8) * 0.3
    }
    if (noteMatRef.current) {
      noteMatRef.current.emissiveIntensity = playing ? 4.2 + Math.sin(t * 3) * 0.8 : 0.5
    }
    if (tvBarsRef.current) {
      tvBarsRef.current.visible = playing
      if (playing) {
        tvBarsRef.current.children.forEach((child, i) => {
          const bar = child as THREE.Mesh
          const h = 0.2 + (Math.sin(t * 4 + i * 0.9) * 0.5 + 0.5) * 0.7
          bar.scale.y = h
          bar.position.y = h * 0.5
        })
      }
    }

    // 4. Now-playing hologram floats above the side table & bobs; panel shimmers.
    if (holoRef.current) {
      holoRef.current.position.y = 1.7 + Math.sin(t * 1.2) * 0.09
    }
    if (holoPanelRef.current) {
      holoPanelRef.current.emissiveIntensity = 3.6 + Math.sin(t * 2.4) * 0.6
    }
  })

  const trackName = playing ? 'Midnight City' : 'SILENCE'
  const trackStatus = playing ? 'Spotify · now playing' : 'Spotify · paused'

  return (
    <group>
      {/* ====================================================================
          1. L-SHAPED SOFA — FREE-STANDING in the room interior (no longer
          pinned to the walls). A clear chunky L: thick seat base + raised
          BACKREST along the back edges + ARMRESTS at the two open ends + an
          L return section, opening toward the room interior (-x / +z).
          Soft amber under-glow on the floor. Click "Relax" (sit).

          Footprint: long run ≈4.6 (in z) along x≈SOFA_CX; return ≈4.0 (in x)
          along z≈SOFA_CZ-2. Heights ≤ ~1.3 (free-standing furniture rule):
          backrest top ≈1.28. Operator sits on the long run facing -x.
      ==================================================================== */}
      {/* Soft amber under-glow plane beneath the sofa footprint. */}
      <mesh position={[SOFA_CX - 0.6, 0.04, SOFA_CZ - 0.8]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[7.0, 7.0]} />
        <meshStandardMaterial
          ref={sofaGlowRef}
          color={PALETTE.amber}
          emissive={PALETTE.amber}
          emissiveIntensity={1.9}
          transparent
          opacity={0.4}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>

      <Interactive
        id="living-sofa"
        label="Relax"
        status="Living Room · lounge"
        position={[SOFA_CX, 0.7, SOFA_CZ]}
        anchor={{ position: [SOFA_CX - 1.7, 0, SOFA_CZ], rotationY: Math.PI / 2, pose: 'sit' }}
        ix={ix}
        accent={PALETTE.amber}
        ringRadius={3.0}
      >
        {/* ---- LONG RUN (runs along z at x≈SOFA_CX, faces -x / interior) ---- */}
        {/* Thick seat base block. */}
        <RoundedBox args={[1.5, 0.62, 4.6]} radius={0.1} smoothness={4} position={[SOFA_CX, 0.31, SOFA_CZ]} castShadow>
          <meshStandardMaterial color={PALETTE.amber} roughness={0.85} metalness={0.0} emissiveIntensity={0} />
        </RoundedBox>
        {/* Raised BACKREST along the +x (back) edge of the long run. */}
        <RoundedBox args={[0.42, 0.78, 4.6]} radius={0.1} smoothness={4} position={[SOFA_CX + 0.72, 0.88, SOFA_CZ]} castShadow>
          <meshStandardMaterial color={AMBER_SOFT} roughness={0.9} metalness={0.0} emissiveIntensity={0} />
        </RoundedBox>
        {/* Seat cushions on the long run (lighter amber, slightly inset). */}
        <RoundedBox args={[1.18, 0.22, 4.2]} radius={0.07} smoothness={4} position={[SOFA_CX - 0.06, SEAT_TOP_Y - 0.1, SOFA_CZ]}>
          <meshStandardMaterial color={AMBER_SEAT} roughness={0.85} metalness={0.0} emissiveIntensity={0} />
        </RoundedBox>
        {/* ARMREST at the far (-z) end of the long run. */}
        <RoundedBox args={[1.42, 0.5, 0.5]} radius={0.1} smoothness={4} position={[SOFA_CX, 0.74, SOFA_CZ - 2.3]} castShadow>
          <meshStandardMaterial color={AMBER_SOFT} roughness={0.88} metalness={0.0} emissiveIntensity={0} />
        </RoundedBox>

        {/* ---- L RETURN (runs along x at z≈SOFA_CZ-2.0, faces +z / interior) ---- */}
        {/* Thick seat base block of the return wing. */}
        <RoundedBox args={[4.0, 0.62, 1.5]} radius={0.1} smoothness={4} position={[SOFA_CX - 2.75, 0.31, SOFA_CZ - 2.05]} castShadow>
          <meshStandardMaterial color={PALETTE.amber} roughness={0.85} metalness={0.0} emissiveIntensity={0} />
        </RoundedBox>
        {/* Raised BACKREST along the -z (back) edge of the return. */}
        <RoundedBox args={[4.0, 0.78, 0.42]} radius={0.1} smoothness={4} position={[SOFA_CX - 2.75, 0.88, SOFA_CZ - 2.77]} castShadow>
          <meshStandardMaterial color={AMBER_SOFT} roughness={0.9} metalness={0.0} emissiveIntensity={0} />
        </RoundedBox>
        {/* Seat cushions on the return wing. */}
        <RoundedBox args={[3.6, 0.22, 1.18]} radius={0.07} smoothness={4} position={[SOFA_CX - 2.75, SEAT_TOP_Y - 0.1, SOFA_CZ - 2.0]}>
          <meshStandardMaterial color={AMBER_SEAT} roughness={0.85} metalness={0.0} emissiveIntensity={0} />
        </RoundedBox>
        {/* ARMREST at the far (-x) open end of the return. */}
        <RoundedBox args={[0.5, 0.5, 1.42]} radius={0.1} smoothness={4} position={[SOFA_CX - 4.55, 0.74, SOFA_CZ - 2.05]} castShadow>
          <meshStandardMaterial color={AMBER_SOFT} roughness={0.88} metalness={0.0} emissiveIntensity={0} />
        </RoundedBox>
      </Interactive>

      {/* ====================================================================
          2. MEDIA CONSOLE (Spotify) — low wide dark console on the TOP wall.
          Carries the vinyl player, sound-wave visualizer & headphones stand.
          Scaled a bit bigger for the larger Operator.
      ==================================================================== */}
      {/* Console body — flush along TOP wall (z≈-15.4), centred at x≈8. */}
      <RoundedBox args={[6.0, 0.82, 0.95]} radius={0.07} smoothness={4} position={[8.0, 0.41, TOP_WALL_Z + 0.55]} castShadow>
        <meshStandardMaterial color={PALETTE.slateDark} roughness={0.6} metalness={0.12} emissiveIntensity={0} />
      </RoundedBox>
      {/* Amber accent strip on the console front (pulses while playing). */}
      <mesh position={[8.0, 0.6, TOP_WALL_Z + 1.03]}>
        <boxGeometry args={[5.3, 0.07, 0.02]} />
        <meshStandardMaterial
          ref={consoleAccentRef}
          color={PALETTE.amber}
          emissive={PALETTE.amber}
          emissiveIntensity={0.0}
          toneMapped={false}
        />
      </mesh>

      {/* 2a. VINYL PLAYER — black disc + cyan centre; spins while spotify.
          Click "Play / Pause" (press). */}
      <Interactive
        id="living-vinyl"
        label={playing ? 'Pause' : 'Play'}
        status={trackStatus}
        position={[6.3, 0.9, TOP_WALL_Z + 0.55]}
        anchor={{ position: [6.3, 0, TOP_WALL_Z + 2.0], rotationY: Math.PI, pose: 'press' }}
        ix={ix}
        accent={PALETTE.amber}
        ringRadius={1.1}
      >
        {/* Flat black record disc lying on the console top. */}
        <mesh ref={vinylRef} position={[6.3, 0.84, TOP_WALL_Z + 0.55]} rotation={[-Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.62, 0.62, 0.03, 40]} />
          <meshStandardMaterial color={PALETTE.void} roughness={0.4} metalness={0.2} emissiveIntensity={0} />
        </mesh>
        {/* Bright cyan centre. */}
        <mesh position={[6.3, 0.86, TOP_WALL_Z + 0.55]} rotation={[-Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.11, 0.11, 0.03, 24]} />
          <meshStandardMaterial
            ref={vinylCenterRef}
            color={PALETTE.cyan}
            emissive={PALETTE.cyan}
            emissiveIntensity={4}
            toneMapped={false}
          />
        </mesh>
        {/* Tonearm (non-emissive structural detail). */}
        <mesh position={[6.9, 0.88, TOP_WALL_Z + 0.07]} rotation={[0, -0.6, 0]}>
          <boxGeometry args={[0.68, 0.04, 0.05]} />
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.5} metalness={0.4} emissiveIntensity={0} />
        </mesh>
      </Interactive>

      {/* 2b. SOUND-WAVE VISUALIZER — 3 vertical cyan bars on the console top. */}
      <group ref={barsRef} position={[8.4, 0.82, TOP_WALL_Z + 0.55]}>
        {[0, 1, 2].map((i) => (
          <mesh key={i} position={[(i - 1) * 0.32, 0.34, 0]}>
            <boxGeometry args={[0.19, 0.68, 0.19]} />
            <meshStandardMaterial color={PALETTE.cyan} emissive={PALETTE.cyan} emissiveIntensity={3.4} toneMapped={false} />
          </mesh>
        ))}
      </group>

      {/* 2c. HEADPHONES STAND — pedestal + headphones with cyan cups.
          Click "Focus Mode" (reach). Sits on the console top (+x end). */}
      <Interactive
        id="living-headphones"
        label="Focus Mode"
        status="Noise-cancel · deep work"
        position={[10.1, 1.35, TOP_WALL_Z + 0.55]}
        anchor={{ position: [10.1, 0, TOP_WALL_Z + 2.0], rotationY: Math.PI, pose: 'reach' }}
        ix={ix}
        accent={PALETTE.amber}
        ringRadius={1.0}
      >
        {/* Pedestal base + post — rises from the console top (y≈0.82). */}
        <RoundedBox args={[0.56, 0.09, 0.56]} radius={0.04} smoothness={4} position={[10.1, 0.87, TOP_WALL_Z + 0.55]}>
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.6} metalness={0.25} emissiveIntensity={0} />
        </RoundedBox>
        <mesh position={[10.1, 1.25, TOP_WALL_Z + 0.55]}>
          <cylinderGeometry args={[0.07, 0.08, 0.82, 16]} />
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.5} metalness={0.3} emissiveIntensity={0} />
        </mesh>
        {/* Headband — dark torus arc over the post. */}
        <mesh position={[10.1, 1.68, TOP_WALL_Z + 0.55]}>
          <torusGeometry args={[0.3, 0.07, 12, 24, Math.PI]} />
          <meshStandardMaterial color={PALETTE.void} roughness={0.5} metalness={0.2} emissiveIntensity={0} />
        </mesh>
        {/* Glowing cyan ear-cups (cylinders on their sides facing ±x). */}
        <mesh position={[9.8, 1.46, TOP_WALL_Z + 0.55]} rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[0.15, 0.15, 0.13, 20]} />
          <meshStandardMaterial
            ref={(m) => {
              headphoneCupRefs.current[0] = m
            }}
            color={PALETTE.cyan}
            emissive={PALETTE.cyan}
            emissiveIntensity={3}
            toneMapped={false}
          />
        </mesh>
        <mesh position={[10.4, 1.46, TOP_WALL_Z + 0.55]} rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[0.15, 0.15, 0.13, 20]} />
          <meshStandardMaterial
            ref={(m) => {
              headphoneCupRefs.current[1] = m
            }}
            color={PALETTE.cyan}
            emissive={PALETTE.cyan}
            emissiveIntensity={3}
            toneMapped={false}
          />
        </mesh>
      </Interactive>

      {/* ====================================================================
          3. ENTERTAINMENT WALL — large 16:9 screen on the TOP outer wall above
          the console (faces +z). Musical-note icon glows when spotify else dim.
          Equalizer bars dance while playing. Click (point). Scaled bigger.
          Mount: centre y=1.1 (in the 1.0-1.2 band), bezel height 1.18 ⇒
          top = 1.1 + 0.59 = 1.69 < wall 1.7 (fits inside the tall outer wall),
          bottom = 0.51 (clears the console below it).
      ==================================================================== */}
      <Interactive
        id="living-screen"
        label="Entertainment"
        status={playing ? 'Visualizer · live' : 'Standby'}
        position={[8.0, 1.1, TOP_WALL_Z]}
        anchor={{ position: [8.0, 0, TOP_WALL_Z + 2.4], rotationY: Math.PI, pose: 'point' }}
        ix={ix}
        accent={PALETTE.amber}
        ringRadius={2.0}
        tooltipHeight={1.0}
      >
        {/* Bezel + screen mounted flush to the TOP wall inner face, facing +z. */}
        <group position={[8.0, 1.1, TOP_WALL_Z + 0.02]}>
          {/* Dark bezel/frame (top 1.69 < tall wall 1.7). */}
          <RoundedBox args={[3.3, 1.18, 0.14]} radius={0.06} smoothness={4} castShadow>
            <meshStandardMaterial color={PALETTE.void} roughness={0.5} metalness={0.35} emissiveIntensity={0} />
          </RoundedBox>
          {/* Screen face — faint cyan wash (always idling). */}
          <mesh position={[0, 0, 0.08]}>
            <planeGeometry args={[3.04, 1.0]} />
            <meshStandardMaterial
              ref={screenMatRef}
              color="#0a2730"
              emissive={PALETTE.cyan}
              emissiveIntensity={1.4}
              toneMapped={false}
            />
          </mesh>
          {/* Musical-note icon (bright when spotify, dim when silent). */}
          <Text position={[0, 0.1, 0.1]} fontSize={0.66} anchorX="center" anchorY="middle">
            {'♫'}
            <meshStandardMaterial
              ref={noteMatRef}
              color={PALETTE.cyan}
              emissive={PALETTE.cyan}
              emissiveIntensity={4.2}
              toneMapped={false}
            />
          </Text>
          {/* Equalizer bars — only visible + animated while spotify is playing. */}
          <group ref={tvBarsRef} position={[0, -0.4, 0.1]} visible={false}>
            {[0, 1, 2, 3, 4, 5, 6].map((i) => (
              <mesh key={i} position={[(i - 3) * 0.4, 0, 0]}>
                <boxGeometry args={[0.2, 1, 0.02]} />
                <meshStandardMaterial color={PALETTE.cyan} emissive={PALETTE.cyan} emissiveIntensity={3} toneMapped={false} />
              </mesh>
            ))}
          </group>
        </group>
      </Interactive>

      {/* ====================================================================
          4. SIDE TABLE + NOW-PLAYING HOLOGRAM — coffee/side table pulled toward
          the ROOM CENTRE, in front of the open mouth of the L-sofa, with a
          floating translucent cyan panel showing the live track name, bobbing.
          Clickable (point). Free-standing; table ≤ ~0.8 tall.
      ==================================================================== */}
      <Interactive
        id="living-nowplaying"
        label="Now Playing"
        status={trackStatus}
        position={[10.4, 1.2, -11.6]}
        anchor={{ position: [9.0, 0, -11.6], rotationY: Math.PI / 2, pose: 'point' }}
        ix={ix}
        accent={PALETTE.amber}
        ringRadius={1.2}
      >
        {/* Chunky cube side/coffee table — sits on the floor near room centre. */}
        <RoundedBox args={[1.0, 0.74, 1.0]} radius={0.07} smoothness={4} position={[10.4, 0.37, -11.6]} castShadow>
          <meshStandardMaterial color={PALETTE.slateDark} roughness={0.6} metalness={0.12} emissiveIntensity={0} />
        </RoundedBox>
        {/* Thin amber lip on the table top (subtle accent). */}
        <mesh position={[10.4, 0.75, -11.6]}>
          <boxGeometry args={[0.84, 0.03, 0.84]} />
          <meshStandardMaterial color={PALETTE.amber} emissive={PALETTE.amber} emissiveIntensity={2.0} toneMapped={false} />
        </mesh>

        {/* Floating now-playing hologram — bobs via holoRef. */}
        <group ref={holoRef} position={[10.4, 1.7, -11.6]}>
          {/* Translucent cyan projection panel. */}
          <mesh>
            <planeGeometry args={[2.5, 0.88]} />
            <meshStandardMaterial
              ref={holoPanelRef}
              color={PALETTE.cyan}
              emissive={PALETTE.cyan}
              emissiveIntensity={3.6}
              transparent
              opacity={0.42}
              side={THREE.DoubleSide}
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
          {/* Track name (both faces so it reads from anywhere in the room). */}
          <Text position={[0, 0.1, 0.02]} fontSize={0.26} color={PALETTE.whiteLight} anchorX="center" anchorY="middle">
            {trackName}
          </Text>
          <Text
            position={[0, 0.1, -0.02]}
            rotation={[0, Math.PI, 0]}
            fontSize={0.26}
            color={PALETTE.whiteLight}
            anchorX="center"
            anchorY="middle"
          >
            {trackName}
          </Text>
          {/* Small caption line. */}
          <Text position={[0, -0.2, 0.02]} fontSize={0.13} color={PALETTE.cyan} anchorX="center" anchorY="middle">
            {playing ? 'NOW PLAYING' : 'PAUSED'}
          </Text>
          {/* Glowing projector base ring beneath the hologram. */}
          <mesh position={[0, -0.55, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.55, 0.04, 12, 48]} />
            <meshStandardMaterial color={PALETTE.cyan} emissive={PALETTE.cyan} emissiveIntensity={3} toneMapped={false} />
          </mesh>
        </group>
      </Interactive>
    </group>
  )
}
