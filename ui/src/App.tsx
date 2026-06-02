import { Routes, Route } from 'react-router'
import { lazy, Suspense } from 'react'
import Home from './pages/Home'

// The redesigned unified console lives at /panel as a self-contained module.
// The floating orb HUD stays at / (loaded by WebFloatingHUD), untouched.
const ConsoleRoot = lazy(() => import('./console/ConsoleRoot'))

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route
        path="/panel"
        element={
          <Suspense fallback={<div className="h-screen w-screen bg-[#0a0e17]" />}>
            <ConsoleRoot />
          </Suspense>
        }
      />
    </Routes>
  )
}
