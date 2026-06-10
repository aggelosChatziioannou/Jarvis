import { createContext, useContext } from 'react'

// Lets deeply nested consumers (e.g. 3D furniture actions) switch the active
// console page. Provided by ConsoleRoot; defaults to a no-op so components
// render safely outside the shell (tests, storybook).
export const NavigationContext = createContext<(page: string) => void>(() => {})

export function useNavigation(): (page: string) => void {
  return useContext(NavigationContext)
}
