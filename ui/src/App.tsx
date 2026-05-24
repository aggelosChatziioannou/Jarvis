import { Routes, Route } from 'react-router'
import Home from './pages/Home'
import ControlPanel from './components/panel/ControlPanel'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/panel" element={<ControlPanel />} />
    </Routes>
  )
}
