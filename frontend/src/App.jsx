import { useState } from 'react'
import { CheckCircle2, X } from 'lucide-react'
import Sidebar from './components/Sidebar'
import TopBar from './components/TopBar'
import Dashboard from './pages/Dashboard'
import './App.css'

function App() {
  const [activePage, setActivePage] = useState('Overview')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [scanRequested, setScanRequested] = useState(false)

  const navigate = (page) => { setActivePage(page); setSidebarOpen(false) }

  return <div className="app-shell">
    <Sidebar activePage={activePage} onNavigate={navigate} open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
    <div className="app-main"><TopBar onMenu={() => setSidebarOpen(true)} onScan={() => setScanRequested(true)} />
      <Dashboard activePage={activePage} />
    </div>
    {scanRequested && <div className="toast" role="status"><span><CheckCircle2 size={16} /> Scan will be available once the backend is connected.</span><button onClick={() => setScanRequested(false)} aria-label="Dismiss notification"><X size={15} /></button></div>}
  </div>
}

export default App
