import { useEffect, useState } from 'react'
import { CheckCircle2, X } from 'lucide-react'
import AppSidebar from './components/Sidebar'
import AppHeader from './components/TopBar'
import Dashboard from './pages/Dashboard'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Agentation } from 'agentation'

function App() {
  const [activePage, setActivePage] = useState('Overview')
  const [scanRequested, setScanRequested] = useState(false)
  // Sample measurements are the default so the console is reviewable without
  // AWS credentials; ?sample=0 opts back into the live backend.
  const [sampleMode] = useState(() => new URLSearchParams(window.location.search).get('sample') !== '0')

  const navigate = (page) => setActivePage(page)

  useEffect(() => {
    const onNavigate = (event) => navigate(event.detail)
    const onScan = () => setScanRequested(true)
    window.addEventListener('cloudops:navigate', onNavigate)
    window.addEventListener('cloudops:scan', onScan)
    return () => { window.removeEventListener('cloudops:navigate', onNavigate); window.removeEventListener('cloudops:scan', onScan) }
  }, [])

  return (
    <TooltipProvider delayDuration={200}>
      <SidebarProvider>
        <AppSidebar activePage={activePage} onNavigate={navigate} />
        <SidebarInset className="min-w-0">
          <AppHeader sampleMode={sampleMode} />
          <Dashboard activePage={activePage} sampleMode={sampleMode} />
        </SidebarInset>
      </SidebarProvider>

      {scanRequested && (
        <div className="bg-foreground text-background fixed right-5 bottom-5 z-50 flex max-w-[calc(100vw-40px)] items-center gap-4 rounded-lg px-4 py-3 text-sm shadow-lg" role="status">
          <span className="flex items-center gap-2"><CheckCircle2 className="size-4" /> Scan will be available once the backend is connected.</span>
          <button type="button" onClick={() => setScanRequested(false)} aria-label="Dismiss notification" className="opacity-70 hover:opacity-100"><X className="size-4" /></button>
        </div>
      )}

      {process.env.NODE_ENV === 'development' && <Agentation endpoint="http://localhost:4747" />}
    </TooltipProvider>
  )
}

export default App
