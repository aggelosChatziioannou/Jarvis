import { useSceneContext } from '@/console/3d/SceneContext'
import { AlertTriangle } from 'lucide-react'

// Transient feedback for furniture actions that failed (Spotify control,
// reminder write, test tone). Auto-clears via SceneContext's pushNotice.
export default function ActionNotice() {
  const { notice } = useSceneContext()
  if (!notice) return null
  return (
    <div
      className="absolute left-1/2 top-5 z-[60] -translate-x-1/2 flex items-center gap-2 rounded-lg px-4 py-2.5"
      style={{
        maxWidth: 'calc(100vw - 48px)',
        background: 'rgba(17, 24, 39, 0.95)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(251, 191, 36, 0.35)',
        boxShadow: '0 0 18px rgba(251, 191, 36, 0.12)',
      }}
    >
      <AlertTriangle size={14} style={{ color: '#fbbf24' }} className="shrink-0" />
      <span className="text-xs" style={{ color: '#f8fafc' }}>{notice}</span>
    </div>
  )
}
