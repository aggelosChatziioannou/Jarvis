import { Suspense, useRef, useEffect, useMemo } from 'react'
import { Canvas, useThree, useFrame } from '@react-three/fiber'
import { OrbitControls, PerspectiveCamera, ContactShadows } from '@react-three/drei'
import { EffectComposer, Bloom, Vignette, ToneMapping } from '@react-three/postprocessing'
import { ToneMappingMode } from 'postprocessing'
import * as THREE from 'three'

import { useSceneContext } from './SceneContext'
import type { SceneMode, Interaction } from './dollhouseTypes'
import { PALETTE, CAMERA, HALF_W, HALF_D, ROOMS, ROOM_LIST, FOCUS_CONFIG, FOCUS_MAX_POLAR, roomKeyAt } from './sceneConstants'

import HouseStructure from './HouseStructure'
import OperatorCharacter from './OperatorCharacter'
import EntranceFurniture from './furniture/EntranceFurniture'
import LivingFurniture from './furniture/LivingFurniture'
import OfficeFurniture from './furniture/OfficeFurniture'
import WellnessFurniture from './furniture/WellnessFurniture'
import StudioFurniture from './furniture/StudioFurniture'
import ControlFurniture from './furniture/ControlFurniture'
import { DustMotes, FloorReflection, FloatingRoomLabels } from './Atmosphere'
import { NotificationOrbs } from './Interactive'

const LIGHT_CONFIG: Record<SceneMode, { ambient: number; hemi: number; key: number; room: number }> = {
  morning: { ambient: 0.5, hemi: 0.6, key: 1.3, room: 0.95 },
  afternoon: { ambient: 0.68, hemi: 0.82, key: 1.45, room: 1.0 },
  evening: { ambient: 0.38, hemi: 0.5, key: 1.0, room: 1.05 },
  night: { ambient: 0.06, hemi: 0.09, key: 0.18, room: 0.32 },
  focus: { ambient: 0.3, hemi: 0.38, key: 0.8, room: 0.6 },
  away: { ambient: 0.1, hemi: 0.16, key: 0.35, room: 0.4 },
}

function SceneLighting({ mode }: { mode: SceneMode }) {
  const c = LIGHT_CONFIG[mode]
  return (
    <>
      <ambientLight color="#7c8aa3" intensity={c.ambient} />
      <hemisphereLight color="#9fb4d4" groundColor="#0a0e17" intensity={c.hemi} />
      <directionalLight
        position={[22, 38, 18]}
        color="#cde3ff"
        intensity={c.key}
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
        shadow-camera-near={1}
        shadow-camera-far={120}
        shadow-camera-left={-28}
        shadow-camera-right={28}
        shadow-camera-top={28}
        shadow-camera-bottom={-28}
        shadow-bias={-0.0004}
      />
      {ROOM_LIST.map((k) => {
        const r = ROOMS[k]
        return (
          <pointLight
            key={k}
            position={[(r.x0 + r.x1) / 2, 1.7, (r.z0 + r.z1) / 2]}
            color={r.accent}
            intensity={r.ambientIntensity * c.room}
            distance={Math.max(r.x1 - r.x0, r.z1 - r.z0) + 4}
            decay={2}
          />
        )
      })}
    </>
  )
}

function ZoomListener({ controlsRef }: { controlsRef: React.RefObject<any> }) {
  const { camera } = useThree()
  useEffect(() => {
    const handle = (e: Event) => {
      const dir = (e as CustomEvent).detail
      const controls = controlsRef.current
      if (!controls) return
      if (dir === 'reset') {
        camera.position.set(...CAMERA.position)
        controls.target.set(...CAMERA.target)
        controls.update()
      } else if (dir === 'in' || dir === 'out') {
        const toTarget = controls.target.clone().sub(camera.position)
        const len = toTarget.length()
        toTarget.normalize()
        camera.position.addScaledVector(toTarget, len * 0.18 * (dir === 'in' ? 1 : -1))
        controls.update()
      }
    }
    window.addEventListener('dollhouse-zoom', handle)
    return () => window.removeEventListener('dollhouse-zoom', handle)
  }, [camera, controlsRef])
  return null
}

// ---------------------------------------------------------------------------
// FocusCamera — when ON, smoothly flies the camera to a cinematic 3/4 lock on
// the room the Operator is in (follows the active object's room), then releases
// to small user orbit/zoom around that room. OFF returns to the hub overview.
// ---------------------------------------------------------------------------
function FocusCamera({
  focusMode,
  activeTarget,
  operatorPos,
  controlsRef,
}: {
  focusMode: boolean
  activeTarget: { position: [number, number, number] } | null
  operatorPos: React.RefObject<THREE.Vector3 | null>
  controlsRef: React.RefObject<any>
}) {
  const { camera } = useThree()
  const st = useRef<{ mode: boolean; room: string | null; flying: boolean }>({ mode: false, room: null, flying: false })
  const dPos = useRef(new THREE.Vector3(...CAMERA.position))
  const dTgt = useRef(new THREE.Vector3(...CAMERA.target))

  useFrame((_, delta) => {
    const controls = controlsRef.current
    if (!controls) return

    const ref: [number, number, number] = activeTarget
      ? activeTarget.position
      : [operatorPos.current?.x ?? 0, 0, operatorPos.current?.z ?? 0]
    const room = focusMode ? roomKeyAt(ref) : null

    if (focusMode !== st.current.mode || room !== st.current.room) {
      st.current.mode = focusMode
      st.current.room = room
      st.current.flying = true
      controls.maxPolarAngle = focusMode ? FOCUS_MAX_POLAR : CAMERA.maxPolarAngle
      if (focusMode && room) {
        const f = FOCUS_CONFIG[room as keyof typeof FOCUS_CONFIG]
        dPos.current.set(...f.position)
        dTgt.current.set(...f.target)
      } else {
        dPos.current.set(...CAMERA.position)
        dTgt.current.set(...CAMERA.target)
      }
      controls.enabled = false
    }

    if (st.current.flying) {
      const k = 1 - Math.exp(-3.2 * Math.min(0.05, delta))
      camera.position.lerp(dPos.current, k)
      controls.target.lerp(dTgt.current, k)
      controls.update()
      if (camera.position.distanceTo(dPos.current) < 0.5 && controls.target.distanceTo(dTgt.current) < 0.3) {
        st.current.flying = false
        controls.enabled = true
      }
    }
  })
  return null
}

export default function DollhouseScene() {
  const {
    sceneMode, mood, services,
    activeTarget, setActiveTarget,
    setHovered, hovered,
    notifications, pushNotification, removeNotification,
    focusMode,
  } = useSceneContext()
  const controlsRef = useRef<any>(null)
  const operatorPos = useRef(new THREE.Vector3(0, 1.4, 0))

  const ix: Interaction = useMemo(
    () => ({
      activate: setActiveTarget,
      hover: setHovered,
      notify: pushNotification,
      activeId: activeTarget?.id ?? null,
    }),
    [setActiveTarget, setHovered, pushNotification, activeTarget],
  )

  const fp = { services, mood, ix }

  return (
    <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', zIndex: 1 }}>
      <Canvas
        shadows={{ type: THREE.PCFShadowMap }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        dpr={[1, 1.5]}
        onPointerMissed={() => setActiveTarget(null)}
      >
        <color attach="background" args={[PALETTE.void]} />
        <fog attach="fog" args={[PALETTE.void, 70, 150]} />

        <PerspectiveCamera makeDefault position={CAMERA.position} fov={CAMERA.fov} near={CAMERA.near} far={CAMERA.far} />
        <SceneLighting mode={sceneMode} />

        <Suspense fallback={null}>
          <HouseStructure />
          <EntranceFurniture {...fp} />
          <LivingFurniture {...fp} />
          <OfficeFurniture {...fp} />
          <WellnessFurniture {...fp} />
          <StudioFurniture {...fp} />
          <ControlFurniture {...fp} />
          <OperatorCharacter activeTarget={activeTarget} mood={mood} hovered={hovered} operatorPos={operatorPos} />
          <NotificationOrbs notifications={notifications} operatorPos={operatorPos} onDone={removeNotification} />

          <FloorReflection />
          <DustMotes />
          <FloatingRoomLabels />
        </Suspense>

        <ContactShadows
          position={[0, 0.015, 0]}
          scale={Math.max(HALF_W, HALF_D) * 2 + 8}
          resolution={512}
          frames={1}
          far={7}
          blur={2.6}
          opacity={0.5}
          color="#000000"
        />

        <OrbitControls
          ref={controlsRef}
          enablePan={false}
          minPolarAngle={CAMERA.minPolarAngle}
          maxPolarAngle={CAMERA.maxPolarAngle}
          minDistance={CAMERA.minDistance}
          maxDistance={CAMERA.maxDistance}
          target={CAMERA.target}
          enableDamping
          dampingFactor={0.05}
          zoomSpeed={0.6}
        />
        <ZoomListener controlsRef={controlsRef} />
        <FocusCamera focusMode={focusMode} activeTarget={activeTarget} operatorPos={operatorPos} controlsRef={controlsRef} />

        <EffectComposer enableNormalPass={false} multisampling={2}>
          <Bloom luminanceThreshold={0.8} luminanceSmoothing={0.18} intensity={0.85} radius={0.7} mipmapBlur />
          <Vignette offset={0.26} darkness={0.6} />
          <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
        </EffectComposer>
      </Canvas>
    </div>
  )
}
