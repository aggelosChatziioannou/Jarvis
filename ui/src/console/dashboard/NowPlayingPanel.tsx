import { useSceneContext } from '@/console/3d/SceneContext'
import { useDashboardDataCtx } from '@/console/services/DashboardDataContext'
import { spotifyControl } from '@/console/services/dashboardApi'
import { SkipBack, SkipForward, Play, Pause, X } from 'lucide-react'

export default function NowPlayingPanel() {
  const { openPanel, setOpenPanel } = useSceneContext()
  const { services } = useDashboardDataCtx()
  if (openPanel !== 'nowplaying') return null

  const sp = services.find((s) => s.id === 'spotify')
  const connected = sp?.connected ?? false
  const playing = sp?.is_playing ?? sp?.active ?? false

  return (
    <div
      className="absolute left-1/2 bottom-6 z-50 -translate-x-1/2"
      style={{
        width: 360,
        background: 'rgba(17, 24, 39, 0.95)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(34, 211, 238, 0.15)',
        borderRadius: 12,
        padding: 16,
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#94a3b8', letterSpacing: '0.06em' }}>
          Now Playing
        </h3>
        <button title="Close" onClick={() => setOpenPanel(null)} style={{ color: '#94a3b8' }}>
          <X size={16} />
        </button>
      </div>

      {!connected ? (
        <div className="text-xs" style={{ color: '#475569' }}>Spotify not connected</div>
      ) : (
        <div className="flex items-center gap-3">
          <div className="w-14 h-14 rounded-md overflow-hidden shrink-0" style={{ background: '#0a0e17' }}>
            {sp?.image_url && <img src={sp.image_url} alt="" className="w-full h-full object-cover" />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate" style={{ color: '#f8fafc' }}>{sp?.title || '—'}</div>
            <div className="text-xs truncate" style={{ color: '#94a3b8' }}>{sp?.artist || ''}</div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-center gap-6 mt-4" style={{ color: '#22d3ee' }}>
        <button title="Previous" onClick={() => void spotifyControl('prev')}><SkipBack size={20} /></button>
        <button title={playing ? 'Pause' : 'Play'} onClick={() => void spotifyControl('playpause')}>
          {playing ? <Pause size={24} /> : <Play size={24} />}
        </button>
        <button title="Next" onClick={() => void spotifyControl('next')}><SkipForward size={20} /></button>
      </div>
    </div>
  )
}
