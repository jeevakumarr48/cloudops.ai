import { useMemo, useState } from 'react'
import { CheckCircle2, X } from 'lucide-react'
import AuthDialog from './components/AuthDialog'
import DemoBanner from './components/DemoBanner'
import Sidebar from './components/Sidebar'
import TopBar from './components/TopBar'
import Dashboard from './pages/Dashboard'
import DemoNotice from './pages/DemoNotice'
import Governance from './pages/Governance'
import Operations from './pages/Operations'
import Recommendations from './pages/Recommendations'
import Security from './pages/Security'
import useSession from './hooks/useSession'
import { DEMO_PAGES, DemoContext, initialDemo, rememberDemo } from './demo/demoMode'
import { setDemoMode } from './services/api'
import './App.css'
import './components/governance/governance.css'

// Pages that use the signed-in governance API. The original pages stay in
// Dashboard, which stays mounted so switching pages does not reload them.
const CONSOLE_PAGES = { Governance, Recommendations, Security, Operations }

function startingDemo() {
  const on = initialDemo()
  setDemoMode(on)
  return on
}

function App() {
  const [demo, setDemo] = useState(startingDemo)
  const [activePage, setActivePage] = useState(() => (demo ? 'Governance' : 'Overview'))
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [scanRequested, setScanRequested] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const session = useSession()

  const navigate = (page) => { setActivePage(page); setSidebarOpen(false) }
  const demoValue = useMemo(() => {
    const change = (on) => {
      setDemoMode(on); rememberDemo(on); setDemo(on)
      setActivePage(on ? 'Governance' : 'Overview')
    }
    return { demo, enterDemo: () => change(true), exitDemo: () => change(false) }
  }, [demo])

  const demoOnly = demo && !DEMO_PAGES.includes(activePage)
  const ConsolePage = demo ? (DEMO_PAGES.includes(activePage) ? CONSOLE_PAGES[activePage] : null) : CONSOLE_PAGES[activePage]
  const sessionKey = `${session.me?.user?.id || 'anonymous'}:${demo ? 'demo' : 'live'}`

  return <DemoContext.Provider value={demoValue}>
    <div className="app-shell">
      <Sidebar activePage={activePage} onNavigate={navigate} open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="app-main"><TopBar onMenu={() => setSidebarOpen(true)} onScan={() => setScanRequested(true)} session={session} onSignIn={() => setAuthOpen(true)} />
        <DemoBanner />
        {!demo && <div hidden={Boolean(ConsolePage)}><Dashboard key={sessionKey} activePage={activePage} onSignIn={() => setAuthOpen(true)} /></div>}
        {demoOnly && <DemoNotice key={activePage} page={activePage} onNavigate={navigate} />}
        {ConsolePage && <ConsolePage key={`${activePage}:${sessionKey}`} isOperator={session.isOperator && !demo} onSignIn={() => setAuthOpen(true)} sessionKey={sessionKey} />}
      </div>
      {authOpen && <AuthDialog onClose={() => setAuthOpen(false)} onLogin={session.login} onRegister={session.register} />}
      {scanRequested && <div className="toast" role="status"><span><CheckCircle2 size={16} /> Scan will be available once the backend is connected.</span><button onClick={() => setScanRequested(false)} aria-label="Dismiss notification"><X size={15} /></button></div>}
    </div>
  </DemoContext.Provider>
}

export default App
