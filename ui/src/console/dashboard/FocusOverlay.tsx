import { useSceneContext } from '@/console/3d/SceneContext'

export default function FocusOverlay() {
  const { dndActive } = useSceneContext()
  if (!dndActive) return null
  return (
    <>
      <div
        className="absolute inset-0 z-30 pointer-events-none"
        style={{ background: 'radial-gradient(ellipse at center, rgba(34,211,238,0.04), rgba(10,14,23,0.32))' }}
      />
      <div
        className="absolute top-6 left-1/2 z-50 -translate-x-1/2 flex items-center gap-2"
        style={{
          padding: '6px 14px',
          background: 'rgba(10,14,23,0.8)',
          border: '1px solid rgba(34,211,238,0.35)',
          borderRadius: 999,
          color: '#22d3ee',
          fontFamily: 'JetBrains Mono, monospace',
          fontSize: 11,
          letterSpacing: '0.18em',
          boxShadow: '0 0 18px rgba(34,211,238,0.25)',
        }}
      >
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: '#22d3ee' }} />
        FOCUS
      </div>
    </>
  )
}
