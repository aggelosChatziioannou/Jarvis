import { useEffect, useRef } from 'react'
import { useAudioEngineCtx } from '@/console/context/AudioEngineContext'

export default function WaveformBand() {
  const { timeRef, levelRef, vadRef } = useAudioEngineCtx()
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    let raf = 0
    const draw = () => {
      const dpr = window.devicePixelRatio || 1
      const w = canvas.clientWidth, h = canvas.clientHeight
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) { canvas.width = w * dpr; canvas.height = h * dpr }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      const data = timeRef.current
      const n = data.length
      const mid = h / 2
      const active = vadRef.current
      const color = active ? '#22d3ee' : '#1e6f7e'
      ctx.lineWidth = 1.5
      ctx.strokeStyle = color
      ctx.shadowColor = color
      ctx.shadowBlur = active ? 8 : 2
      ctx.beginPath()
      for (let i = 0; i < n; i++) {
        const x = (i / (n - 1)) * w
        const y = mid + ((data[i] - 128) / 128) * mid * 0.9
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y)
      }
      ctx.stroke()
      ctx.shadowBlur = 0
      const lvl = Math.min(1, levelRef.current.rms * 3)
      ctx.fillStyle = 'rgba(34,211,238,0.5)'
      ctx.fillRect(w - 60, 6, 56 * lvl, 3)
      ctx.fillStyle = '#475569'
      ctx.font = '8px monospace'
      ctx.fillText('L  R', w - 60, 22)
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [timeRef, levelRef, vadRef])

  return (
    <div className="relative w-full h-full">
      <div className="absolute top-2 left-3 flex items-center gap-1.5 z-10">
        <span className="w-1.5 h-1.5 rounded-full bg-[#22d3ee] animate-glow-pulse" />
        <span className="text-[10px] text-[#94a3b8] tracking-widest uppercase">Live Waveform</span>
      </div>
      <canvas ref={canvasRef} className="w-full h-full" />
    </div>
  )
}
