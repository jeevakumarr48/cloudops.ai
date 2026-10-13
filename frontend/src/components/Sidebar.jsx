import { BarChart3, Bot, Boxes, Cloud, Cog, FileCode2, LayoutDashboard, ShieldCheck } from 'lucide-react'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@/components/ui/sidebar'

const groups = [
  { label: 'Monitor', items: [['Overview', LayoutDashboard], ['Resources', Boxes], ['Cost Analysis', BarChart3], ['AI Insights', Bot]] },
  { label: 'Govern', items: [['IaC Review', FileCode2], ['Governance', ShieldCheck]] },
]

function AppSidebar({ activePage, onNavigate }) {
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" onClick={() => onNavigate('Overview')} tooltip="CloudOps AI">
              <div className="bg-primary text-primary-foreground flex aspect-square size-8 items-center justify-center rounded-lg">
                <Cloud className="size-4" />
              </div>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-semibold">CloudOps AI</span>
                <span className="text-muted-foreground truncate text-xs">Cloud Intelligence Platform</span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        {groups.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map(([label, Icon]) => (
                  <SidebarMenuItem key={label}>
                    <SidebarMenuButton isActive={activePage === label} onClick={() => onNavigate(label)} tooltip={label}>
                      <Icon />
                      <span>{label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton isActive={activePage === 'Settings'} onClick={() => onNavigate('Settings')} tooltip="Settings">
              <Cog />
              <span>Settings</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  )
}

export default AppSidebar
