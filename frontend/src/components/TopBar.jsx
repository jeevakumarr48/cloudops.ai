import { useEffect, useState } from 'react'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import { SidebarTrigger } from '@/components/ui/sidebar'
import StatusPill from './StatusPill'
import { getHealth } from '../services/api'

function AppHeader({ sampleMode = false }) {
  const [connection, setConnection] = useState(() => (sampleMode ? 'sample' : 'checking'))

  useEffect(() => {
    if (sampleMode) return undefined
    let active = true
    getHealth()
      .then(() => { if (active) setConnection('connected') })
      .catch(() => { if (active) setConnection('offline') })
    return () => { active = false }
  }, [sampleMode])

  const status = {
    checking: { tone: 'neutral', label: 'Checking' },
    connected: { tone: 'ok', label: 'Connected' },
    offline: { tone: 'amber', label: 'Offline' },
    sample: { tone: 'blue', label: 'Sample' },
  }[connection]

  return (
    <header className="bg-background/80 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-10 flex h-16 shrink-0 items-center gap-2 border-b px-4 backdrop-blur md:px-6">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-1 !h-5 max-sm:hidden" />
      <span className="hidden font-semibold sm:inline">CloudOps AI</span>
      <span className="text-muted-foreground hidden text-sm sm:inline">AWS Account</span>
      <StatusPill tone={status.tone} title="Live connectivity to the CloudOps AI API (/health)">{status.label}</StatusPill>
      <div className="ml-auto flex items-center gap-2 md:gap-3">
        <span className="text-muted-foreground hidden text-sm sm:inline">Region <span className="text-foreground font-medium">—</span></span>
        <Button onClick={() => window.dispatchEvent(new CustomEvent('cloudops:scan'))}>Add a scan</Button>
      </div>
    </header>
  )
}

export default AppHeader
