import { useEffect, useRef } from 'react'
import { Mic } from 'lucide-react'
import { useAudioEngineCtx } from '@/console/context/AudioEngineContext'
import { useAssistantAudioCtx } from '@/console/services/AssistantAudioContext'
import { statusDisplay } from '@/console/lib/statusMap'

export default function AudioOrb() {
  const { levelRef, vadRef, permission, running, enable } = useAudioEngineCtx()
  const { state: assistantState, connected } = useAssistantAudioCtx()
  const status = statusDisplay(assistantState, connected)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    let raf = 0
    let t = 0
    const draw = () => {
      t += 0.016
      const dpr = window.devicePixelRatio || 1
      const size = Math.min(canvas.clientWidth, canvas.clientHeight)
      if (canvas.width !== size * dpr || canvas.height !== size * dpr) {
        canvas.width = size * dpr
        canvas.height = size * dpr
      }
      if (size < 4) { raf = requestAnimationFrame(draw); return }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, size, size)
      const cx = size / 2
      const cy = size / 2
      const level = Math.min(1, levelRef.current.rms * 3)
      const active = vadRef.current
      const base = size * 0.16
      const glowColor = active ? '#22d3ee' : '#3b82a6'

      for (let i = 0; i < 3; i++) {
        const phase = (t + i * 1.3) % 4
        const r = base + phase * (size * 0.06) + level * size * 0.12
        const alpha = Math.max(0, 0.28 - phase * 0.06) * (0.4 + level)
        ctx.beginPath()
        ctx.arc(cx, cy, r, 0, Math.PI * 2)
        ctx.strokeStyle = `rgba(34,211,238,${alpha})`
        ctx.lineWidth = 1.5
        ctx.stroke()
      }

      const coreR = Math.max(0, base + level * size * 0.10 + Math.sin(t * 2) * 2)
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR)
      grad.addColorStop(0, active ? 'rgba(34,211,238,0.9)' : 'rgba(59,130,166,0.7)')
      grad.addColorStop(1, 'rgba(34,211,238,0)')
      ctx.fillStyle = grad
      ctx.shadowColor = glowColor
      ctx.shadowBlur = 20 + level * 30
      ctx.beginPath()
      ctx.arc(cx, cy, coreR, 0, Math.PI * 2)
      ctx.fill()
      ctx.shadowBlur = 0

      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [levelRef, vadRef])

  const needsPermission = permission !== 'granted'

  return (
    <div className="relative w-full h-full flex flex-col items-center justify-center">
      <canvas ref={canvasRef} className="w-full h-full absolute inset-0" />
      <div className="absolute top-3 left-3 flex items-center gap-1.5 z-10">
        <span
          className={`w-1.5 h-1.5 rounded-full ${running ? 'bg-[#22d3ee] animate-glow-pulse' : 'bg-[#475569]'}`}
        />
        <span className="text-[10px] text-[#94a3b8] tracking-widest uppercase">
          {running ? 'Mic preview' : 'Preview off'}
        </span>
      </div>
      {needsPermission && (
        <button
          onClick={() => void enable()}
          className="z-10 flex items-center gap-2 px-4 py-2 rounded-full text-[12px] font-semibold transition-all"
          style={{
            background: 'rgba(34,211,238,0.12)',
            color: '#22d3ee',
            border: '1px solid rgba(34,211,238,0.3)',
          }}
        >
          <Mic size={14} /> Enable microphone
        </button>
      )}
      <div className="absolute bottom-3 z-10 flex flex-col items-center gap-0.5">
        <span
          className="text-[11px] tracking-widest uppercase font-semibold"
          style={{ color: status.color }}
        >
          {status.label}
        </span>
        <span className="text-[8px] text-[#475569] tracking-widest uppercase">assistant</span>
      </div>
    </div>
  )
}
