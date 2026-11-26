import { useState } from 'react'
import { CheckCircle2, X } from 'lucide-react'
import AuthDialog from './components/AuthDialog'
import Sidebar from './components/Sidebar'
import TopBar from './components/TopBar'
import Dashboard from './pages/Dashboard'
import Governance from './pages/Governance'
import Recommendations from './pages/Recommendations'
import useSession from './hooks/useSession'
import './App.css'
import './components/governance/governance.css'

// Pages that use the signed-in governance API. The original pages stay in
// Dashboard, which stays mounted so switching pages does not reload them.
const CONSOLE_PAGES = { Governance, Recommendations }

function App() {
  const [activePage, setActivePage] = useState('Overview')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [scanRequested, setScanRequested] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const session = useSession()

  const navigate = (page) => { setActivePage(page); setSidebarOpen(false) }
  const ConsolePage = CONSOLE_PAGES[activePage]
  const sessionKey = session.me?.user?.id || 'anonymous'

  return <div className="app-shell">
    <Sidebar activePage={activePage} onNavigate={navigate} open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
    <div className="app-main"><TopBar onMenu={() => setSidebarOpen(true)} onScan={() => setScanRequested(true)} session={session} onSignIn={() => setAuthOpen(true)} />
      <div hidden={Boolean(ConsolePage)}><Dashboard activePage={activePage} /></div>
      {ConsolePage && <ConsolePage key={activePage} isOperator={session.isOperator} onSignIn={() => setAuthOpen(true)} sessionKey={sessionKey} />}
    </div>
    {authOpen && <AuthDialog onClose={() => setAuthOpen(false)} onLogin={session.login} onRegister={session.register} />}
    {scanRequested && <div className="toast" role="status"><span><CheckCircle2 size={16} /> Scan will be available once the backend is connected.</span><button onClick={() => setScanRequested(false)} aria-label="Dismiss notification"><X size={15} /></button></div>}
  </div>
}

export default App
