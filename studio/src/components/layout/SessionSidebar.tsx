import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'

export function SessionSidebar() {

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex items-center gap-2.5 py-2 px-3 rounded-md text-[13px] font-medium transition-colors',
      isActive ? 'bg-primary/10 text-primary border-l-2 border-primary' : 'text-text-muted hover:text-text-light hover:bg-white/5'
    )

  return (
    <section className="w-64 flex flex-col bg-dark-sidebar border-r border-border-subtle flex-shrink-0">
      <div className="pl-4 pr-3 py-3 border-b border-border-subtle flex items-center">
        <h2 className="font-bold text-nav-label uppercase tracking-[0.1em] text-text-muted">
          hippomem
        </h2>
      </div>

      <div className="flex-1 overflow-y-auto py-3 px-4">
        <div className="pl-2 space-y-0.5">
          <NavLink to="/" className={navLinkClass}>
            <span className="material-symbols-outlined !text-lg">home</span>
            Dashboard
          </NavLink>
          <NavLink to="/chat" className={navLinkClass}>
            <span className="material-symbols-outlined !text-lg">chat</span>
            Chat
          </NavLink>
          <NavLink to="/memory" className={navLinkClass}>
            <span className="material-symbols-outlined !text-lg">psychology</span>
            Memory
          </NavLink>
          <NavLink to="/self" className={navLinkClass}>
            <span className="material-symbols-outlined !text-lg">person</span>
            Self
          </NavLink>
          <NavLink to="/personas" className={navLinkClass}>
            <span className="material-symbols-outlined !text-lg">group</span>
            Entities
          </NavLink>
          <NavLink to="/traces" className={navLinkClass}>
            <span className="material-symbols-outlined !text-lg">bug_report</span>
            Inspector
          </NavLink>
          <NavLink to="/settings" className={navLinkClass}>
            <span className="material-symbols-outlined !text-lg">settings</span>
            Settings
          </NavLink>
        </div>
      </div>
    </section>
  )
}
