import { useState, useCallback, lazy, Suspense } from 'react'
import TitleBar from '@/console/components/shell/TitleBar'
import Sidebar from '@/console/components/shell/Sidebar'
import StatusBar from '@/console/components/shell/StatusBar'

const DashboardPage = lazy(() => import('@/console/sections/DashboardPage'))
const MemoryPage = lazy(() => import('@/console/sections/MemoryPage'))
const AudioPage = lazy(() => import('@/console/sections/AudioPage'))
const LogsPage = lazy(() => import('@/console/sections/LogsPage'))

const PAGE_TITLES: Record<string, string> = {
  dashboard: 'Dashboard',
  memory: 'Memory',
  audio: 'Audio I/O',
  logs: 'Live Logs',
}

export default function ConsoleRoot() {
  const [activePage, setActivePage] = useState('dashboard')
  const handleNavigate = useCallback((page: string) => setActivePage(page), [])

  return (
    <div className="h-screen w-screen bg-[#0a0e17] flex flex-col overflow-hidden">
      <TitleBar pageTitle={PAGE_TITLES[activePage] ?? 'Console'} />
      <div className="flex flex-1 min-h-0">
        <Sidebar activePage={activePage} onNavigate={handleNavigate} />
        <main className="flex-1 min-w-0 overflow-hidden relative">
          <Suspense fallback={<PageFallback />}>
            {activePage === 'dashboard' && <DashboardPage />}
            {activePage !== 'dashboard' && (
              <div className="h-full p-6 overflow-hidden">
                {activePage === 'memory' && <MemoryPage />}
                {activePage === 'audio' && <AudioPage />}
                {activePage === 'logs' && <LogsPage />}
              </div>
            )}
          </Suspense>
        </main>
      </div>
      <StatusBar />
    </div>
  )
}

function PageFallback() {
  return (
    <div className="h-full w-full flex items-center justify-center bg-[#0a0e17]">
      <p className="text-[#94a3b8] text-sm">Loading…</p>
    </div>
  )
}
