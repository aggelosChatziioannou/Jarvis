import { useEffect, useRef } from 'react'
import { useThree } from '@react-three/fiber'
import { CAMERA, HALF_W, HALF_D } from './sceneConstants'

const MARGIN = 2.5 // world units beyond the house footprint

// Keeps the whole dollhouse in frame as the window aspect changes. The
// vertical FOV is fixed, so narrow windows shrink the horizontal FOV and
// would crop the house; we move the camera back along its current direction
// just enough to fit. Manual zoom is respected: we only auto-shrink back to
// a distance we previously auto-set (so user zoom-ins are never fought).
export default function ResponsiveFraming() {
  const camera = useThree((s) => s.camera)
  const size = useThree((s) => s.size)
  const lastAuto = useRef<number | null>(null)

  useEffect(() => {
    const aspect = size.width / Math.max(1, size.height)
    const halfV = (CAMERA.fov * Math.PI) / 360
    const tanV = Math.tan(halfV)
    const needDepth = (HALF_D + MARGIN) / tanV
    const needWidth = (HALF_W + MARGIN) / (tanV * aspect)
    const required = Math.min(Math.max(needDepth, needWidth, CAMERA.minDistance), CAMERA.maxDistance)

    const current = camera.position.length()
    const userZoomed = lastAuto.current !== null && Math.abs(current - lastAuto.current) > 0.5
    if (required > current + 0.25 || (!userZoomed && Math.abs(required - current) > 0.25)) {
      camera.position.setLength(required)
      lastAuto.current = required
    }
  }, [camera, size.width, size.height])

  return null
}
