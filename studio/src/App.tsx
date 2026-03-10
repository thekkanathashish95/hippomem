import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom'
import { TooltipProvider } from '@/components/ui/tooltip'
import { SessionSidebar } from '@/components/layout/SessionSidebar'
import { ChatLayout } from '@/components/layout/ChatLayout'
import { MemoryLayout } from '@/components/layout/MemoryLayout'
import { DashboardLayout } from '@/components/layout/DashboardLayout'
import { TracesLayout } from '@/components/layout/TracesLayout'
import { SettingsLayout } from '@/components/layout/SettingsLayout'
import { SelfLayout } from '@/components/layout/SelfLayout'
import { PersonaLayout } from '@/components/layout/PersonaLayout'
import { api } from '@/services/api'

function SetupGuard() {
  const navigate = useNavigate()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    api.getHealth()
      .then((h) => {
        if (h.setup_required) navigate('/settings', { replace: true })
        else setReady(true)
      })
      .catch(() => setReady(true))
  }, [navigate])

  if (!ready) return null
  return <DashboardLayout />
}

function App() {
  return (
    <TooltipProvider delayDuration={200} skipDelayDuration={0}>
      <BrowserRouter>
        <div className="flex h-screen w-full overflow-hidden bg-pure-black">
          <SessionSidebar />
          <Routes>
            <Route path="/" element={<SetupGuard />} />
            <Route path="/chat" element={<ChatLayout />} />
            <Route path="/memory" element={<MemoryLayout />} />
            <Route path="/self" element={<SelfLayout />} />
            <Route path="/personas" element={<PersonaLayout />} />
            <Route path="/traces" element={<TracesLayout />} />
            <Route path="/settings" element={<SettingsLayout />} />
          </Routes>
        </div>
      </BrowserRouter>
    </TooltipProvider>
  )
}

export default App
