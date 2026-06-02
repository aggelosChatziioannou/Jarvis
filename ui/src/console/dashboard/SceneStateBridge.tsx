import { useEffect } from 'react'
import { useSceneContext } from '@/console/3d/SceneContext'
import { useDashboardDataCtx } from '@/console/services/DashboardDataContext'
import type { SystemMood } from '@/console/3d/dollhouseTypes'

// Drives the 3D scene from the real assistant: the Operator's mood follows the
// live voice state, and service furniture glows reflect /api/services/status.
// (The StatePanel "TESTING" toggles remain a manual override between polls.)

function moodFromState(state: string | null | undefined): SystemMood {
  switch (state) {
    case 'listening':
    case 'thinking':
    case 'synthesizing':
      return 'processing'
    case 'speaking':
      return 'busy'
    default:
      return 'idle'
  }
}

export default function SceneStateBridge() {
  const { setMood, setServices } = useSceneContext()
  const { state, services } = useDashboardDataCtx()

  const vs = state?.state
  useEffect(() => {
    setMood(moodFromState(vs))
  }, [vs, setMood])

  const spotify = services.find((s) => s.id === 'spotify')?.connected ?? false
  const remindersPending = services.find((s) => s.id === 'reminders')?.count ?? 0
  const active = vs === 'listening' || vs === 'thinking' || vs === 'speaking'

  useEffect(() => {
    setServices({
      spotify,
      gmailUnread: 0, // real unread count lands in Phase 6 (Gmail OAuth)
      calendarAlert: false,
      weatherAlert: false,
      taskActive: remindersPending > 0,
      processing: active,
    })
  }, [spotify, remindersPending, active, setServices])

  return null
}
