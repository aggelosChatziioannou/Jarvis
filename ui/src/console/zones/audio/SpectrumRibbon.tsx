import { useEffect, useRef } from 'react'
import { useAudioEngineCtx } from '@/console/context/AudioEngineContext'

const BARS = 28
const COLORS = ['#22d3ee', '#38bdf8', '#a78bfa', '#fbbf24', '#fb7185']

export default function SpectrumRibbon() {
  const { freqRef } = useAudioEngineCtx()
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
      const data = freqRef.current
      const step = Math.floor(data.length / BARS) || 1
      const barW = w / BARS
      for (let b = 0; b < BARS; b++) {
        let sum = 0
        for (let k = 0; k < step; k++) sum += data[b * step + k] || 0
        const mag = sum / step / 255
        const barH = Math.max(2, mag * h)
        const color = COLORS[Math.min(COLORS.length - 1, Math.floor((b / BARS) * COLORS.length))]
        ctx.fillStyle = color
        ctx.globalAlpha = 0.35 + mag * 0.65
        ctx.fillRect(b * barW + 1, h - barH, barW - 2, barH)
      }
      ctx.globalAlpha = 1
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [freqRef])

  return (
    <div className="relative w-full h-full">
      <div className="absolute top-2 left-3 text-[10px] text-[#94a3b8] tracking-widest uppercase z-10">Frequency</div>
      <canvas ref={canvasRef} className="w-full h-full" />
    </div>
  )
}
