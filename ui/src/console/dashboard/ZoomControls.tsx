import { ZoomIn, ZoomOut, RotateCcw, Focus } from 'lucide-react'
import { useSceneContext } from '@/console/3d/SceneContext'

function sendZoom(dir: 'in' | 'out' | 'reset') {
  window.dispatchEvent(new CustomEvent('dollhouse-zoom', { detail: dir }))
}

export default function ZoomControls() {
  const { focusMode, toggleFocusMode } = useSceneContext()
  return (
    <div
      className="absolute top-20 right-6 z-30 flex flex-col gap-2 rounded-xl p-2"
      style={{
        background: 'rgba(17, 24, 39, 0.85)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(34, 211, 238, 0.15)',
      }}
    >
      <button
        onClick={() => sendZoom('in')}
        className="flex h-10 w-10 items-center justify-center rounded-lg transition-all duration-150 hover:scale-105 active:scale-95"
        style={{
          background: 'rgba(34, 211, 238, 0.1)',
          color: '#22d3ee',
          border: '1px solid rgba(34, 211, 238, 0.2)',
        }}
        title="Zoom In"
      >
        <ZoomIn size={20} />
      </button>
      <button
        onClick={() => sendZoom('out')}
        className="flex h-10 w-10 items-center justify-center rounded-lg transition-all duration-150 hover:scale-105 active:scale-95"
        style={{
          background: 'rgba(34, 211, 238, 0.1)',
          color: '#22d3ee',
          border: '1px solid rgba(34, 211, 238, 0.2)',
        }}
        title="Zoom Out"
      >
        <ZoomOut size={20} />
      </button>
      <button
        onClick={() => sendZoom('reset')}
        className="flex h-10 w-10 items-center justify-center rounded-lg transition-all duration-150 hover:scale-105 active:scale-95"
        style={{
          background: 'rgba(34, 211, 238, 0.1)',
          color: '#22d3ee',
          border: '1px solid rgba(34, 211, 238, 0.2)',
        }}
        title="Reset View"
      >
        <RotateCcw size={18} />
      </button>

      {/* Room Focus toggle */}
      <button
        onClick={toggleFocusMode}
        className="flex h-10 w-10 items-center justify-center rounded-lg transition-all duration-150 hover:scale-105 active:scale-95"
        style={{
          background: focusMode ? 'rgba(34, 211, 238, 0.85)' : 'rgba(34, 211, 238, 0.1)',
          color: focusMode ? '#0a0e17' : '#22d3ee',
          border: '1px solid rgba(34, 211, 238, 0.35)',
          boxShadow: focusMode ? '0 0 16px rgba(34,211,238,0.5)' : 'none',
        }}
        title={focusMode ? 'Exit Room Focus' : 'Room Focus (follow the Operator)'}
      >
        <Focus size={18} />
      </button>

      <div
        className="mt-1 text-center font-mono-data"
        style={{ fontSize: '9px', color: focusMode ? '#22d3ee' : '#64748b', letterSpacing: '1px' }}
      >
        {focusMode ? 'FOCUS' : 'HUB'}
      </div>
    </div>
  )
}
