import { useCallback } from 'react'
import { useSceneContext } from '@/console/3d/SceneContext'
import { resolveAction, planFurnitureEffects } from '@/console/3d/furnitureActions'
import { spotifyControl, createQuickReminder, playTestTone } from '@/console/services/dashboardApi'
import { useNavigation } from '@/console/services/NavigationContext'

// Returns the `arrive(id)` handler: when the Operator reaches a furniture
// object, look up its action and execute the planned effects. Side-effecting
// shell around the pure planFurnitureEffects().
export function useFurnitureActions(): (id: string) => void {
  const { services, toggleService, dndActive, toggleDnd, setOpenPanel, toggleNightMode } = useSceneContext()
  const navigate = useNavigation()

  return useCallback(
    (id: string) => {
      const action = resolveAction(id)
      if (!action) return
      const effects = planFurnitureEffects(action, { spotifyPlaying: services.spotify, dndActive })
      for (const e of effects) {
        if (e.type === 'openPanel') {
          setOpenPanel(e.panel)
        } else if (e.type === 'navigate') {
          navigate(e.page)
        } else if (e.type === 'toggleDnd') {
          toggleDnd()
        } else if (e.type === 'toggleLights') {
          toggleNightMode()
        } else if (e.type === 'createReminder') {
          void createQuickReminder(e.label, e.afterMinutes)
        } else if (e.type === 'testTone') {
          void playTestTone()
        } else if (e.type === 'pauseMusic') {
          toggleService('spotify') // optimistic: vinyl stops spinning now
          void spotifyControl('playpause')
        } else if (e.type === 'spotify') {
          if (e.optimisticToggle) toggleService('spotify')
          void spotifyControl(e.op).then((r) => {
            if (!r.ok && e.optimisticToggle) toggleService('spotify') // revert on failure
          })
        }
      }
    },
    [services.spotify, dndActive, toggleService, toggleDnd, setOpenPanel, toggleNightMode, navigate],
  )
}
