import { useState, useEffect, useCallback } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { NAV, ANALYTICS_NAV, ADMIN_NAV } from '../lib/navigation'
import type { NavItem } from '../lib/navigation'

const STORAGE_KEY = 'mfi_sidebar_collapsed'
const SECTIONS_KEY = 'mfi_sidebar_sections'

interface SidebarProps {
  mobileOpen: boolean
  onMobileClose: () => void
  collapsed: boolean
  onToggleCollapse: () => void
}

function NavIcon({ d }: { d: string }) {
  return (
    <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  )
}

function SidebarSection({
  title,
  items,
  collapsed,
  open,
  onToggle,
  onNavClick,
}: {
  title: string
  items: NavItem[]
  collapsed: boolean
  open: boolean
  onToggle: () => void
  onNavClick?: () => void
}) {
  const location = useLocation()
  const hasActive = items.some(
    (item) => item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to),
  )

  return (
    <div>
      {!collapsed && (
        <button
          onClick={onToggle}
          className={`w-full flex items-center justify-between px-3 py-2 text-[10px] font-semibold uppercase tracking-wider transition-colors ${
            hasActive ? 'text-blue-400' : 'text-gray-500 hover:text-gray-300'
          }`}
          aria-expanded={open}
        >
          {title}
          <svg
            className={`w-3 h-3 transition-transform ${open ? '' : '-rotate-90'}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      )}
      {(collapsed || open) && (
        <nav className="space-y-0.5 px-2" aria-label={`${title} navigation`}>
          {items.map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={onNavClick}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-md transition-colors text-sm ${
                  collapsed ? 'justify-center px-2 py-2' : 'px-3 py-1.5'
                } ${
                  isActive
                    ? 'bg-blue-600/20 text-blue-400'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`
              }
            >
              <NavIcon d={icon} />
              {!collapsed && <span className="truncate">{label}</span>}
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  )
}

export function useSidebarCollapsed() {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
      return false
    }
  })

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(STORAGE_KEY, String(next))
      } catch { /* ignore */ }
      return next
    })
  }, [])

  return { collapsed, toggle }
}

export default function Sidebar({ mobileOpen, onMobileClose, collapsed, onToggleCollapse }: SidebarProps) {
  const [sections, setSections] = useState<Record<string, boolean>>(() => {
    try {
      const saved = localStorage.getItem(SECTIONS_KEY)
      return saved ? JSON.parse(saved) : { main: true, analytics: true, admin: true }
    } catch {
      return { main: true, analytics: true, admin: true }
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(SECTIONS_KEY, JSON.stringify(sections))
    } catch { /* ignore */ }
  }, [sections])

  const toggleSection = (key: string) => {
    setSections((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const sidebarContent = (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto py-3 space-y-4">
        <SidebarSection
          title="Main"
          items={NAV}
          collapsed={collapsed}
          open={sections.main}
          onToggle={() => toggleSection('main')}
          onNavClick={mobileOpen ? onMobileClose : undefined}
        />
        <SidebarSection
          title="Analytics"
          items={ANALYTICS_NAV}
          collapsed={collapsed}
          open={sections.analytics}
          onToggle={() => toggleSection('analytics')}
          onNavClick={mobileOpen ? onMobileClose : undefined}
        />
        <SidebarSection
          title="Admin"
          items={ADMIN_NAV}
          collapsed={collapsed}
          open={sections.admin}
          onToggle={() => toggleSection('admin')}
          onNavClick={mobileOpen ? onMobileClose : undefined}
        />
      </div>

      {/* Collapse toggle (desktop only) */}
      <div className="hidden lg:block border-t border-gray-800 p-2">
        <button
          onClick={onToggleCollapse}
          className="w-full flex items-center justify-center py-2 text-gray-500 hover:text-white transition-colors rounded-md hover:bg-gray-800"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <svg
            className={`w-5 h-5 transition-transform ${collapsed ? 'rotate-180' : ''}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </button>
      </div>
    </div>
  )

  return (
    <>
      {/* Desktop sidebar */}
      <aside
        className={`hidden lg:flex flex-col fixed left-0 top-12 h-[calc(100vh-3rem)] bg-gray-900 border-r border-gray-800 z-40 transition-[width] duration-200 ${
          collapsed ? 'w-16' : 'w-56'
        }`}
      >
        {sidebarContent}
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <>
          <div
            className="lg:hidden fixed inset-0 bg-black/50 z-40"
            onClick={onMobileClose}
            aria-hidden="true"
          />
          <aside className="lg:hidden fixed left-0 top-12 h-[calc(100vh-3rem)] w-56 bg-gray-900 border-r border-gray-800 z-40 overflow-hidden">
            {sidebarContent}
          </aside>
        </>
      )}
    </>
  )
}
