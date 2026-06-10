import { Suspense, lazy } from 'react'
import { SceneProvider } from '@/console/3d/SceneContext'
import { DashboardDataProvider } from '@/console/services/DashboardDataContext'
import SceneStateBridge from '@/console/dashboard/SceneStateBridge'
import ZoomControls from '@/console/dashboard/ZoomControls'
import StatePanel from '@/console/dashboard/StatePanel'
import SystemStatusPanel from '@/console/dashboard/SystemStatusPanel'
import NowPlayingPanel from '@/console/dashboard/NowPlayingPanel'
import InfoPanel from '@/console/dashboard/InfoPanel'
import FocusOverlay from '@/console/dashboard/FocusOverlay'

const DollhouseScene = lazy(() => import('@/console/3d/DollhouseScene'))

export default function DashboardPage() {
  return (
    <SceneProvider>
      <DashboardDataProvider>
        <SceneStateBridge />
        <div className="relative w-full h-full bg-[#0a0e17] overflow-hidden">
          <Suspense fallback={<SceneFallback />}>
            <DollhouseScene />
          </Suspense>
          <ZoomControls />
          <StatePanel />
          <SystemStatusPanel />
          <NowPlayingPanel />
          <InfoPanel />
          <FocusOverlay />
        </div>
      </DashboardDataProvider>
    </SceneProvider>
  )
}

function SceneFallback() {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-[#0a0e17]">
      <p className="text-[#94a3b8] text-sm tracking-widest">LOADING 3D CONSOLE…</p>
    </div>
  )
}
