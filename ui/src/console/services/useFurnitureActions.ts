import { useCallback } from 'react'
import { useSceneContext } from '@/console/3d/SceneContext'
import { resolveAction, planFurnitureEffects, friendlyActionFailure } from '@/console/3d/furnitureActions'
import { spotifyControl, createQuickReminder, playTestTone } from '@/console/services/dashboardApi'
import { useNavigation } from '@/console/services/NavigationContext'

// Returns the `arrive(id)` handler: when the Operator reaches a furniture
// object, look up its action and execute the planned effects. Side-effecting
// shell around the pure planFurnitureEffects(). Failures surface as a
// transient notice — the user just watched the Operator press the thing,
// so silence reads as "broken".
export function useFurnitureActions(): (id: string) => void {
  const { services, toggleService, dndActive, toggleDnd, setOpenPanel, toggleNightMode, pushNotice } = useSceneContext()
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
          void createQuickReminder(e.label, e.afterMinutes).then((ok) => {
            if (!ok) pushNotice(friendlyActionFailure('reminder'))
          })
        } else if (e.type === 'testTone') {
          void playTestTone().then((ok) => {
            if (!ok) pushNotice(friendlyActionFailure('tone'))
          })
        } else if (e.type === 'pauseMusic') {
          toggleService('spotify') // optimistic: vinyl stops spinning now
          void spotifyControl('playpause').then((r) => {
            if (!r.ok) pushNotice(friendlyActionFailure('spotify', r.reason))
          })
        } else if (e.type === 'spotify') {
          if (e.optimisticToggle) toggleService('spotify')
          void spotifyControl(e.op).then((r) => {
            if (!r.ok) {
              if (e.optimisticToggle) toggleService('spotify') // revert on failure
              pushNotice(friendlyActionFailure('spotify', r.reason))
            }
          })
        }
      }
    },
    [services.spotify, dndActive, toggleService, toggleDnd, setOpenPanel, toggleNightMode, navigate, pushNotice],
  )
}
