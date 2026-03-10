import type { ViewMode } from '@/stores/memoryStore'
import { cn } from '@/lib/utils'

interface ViewToggleProps {
  activeView: ViewMode
  onViewChange: (view: ViewMode) => void
}

const views: { id: ViewMode; label: string; icon: string }[] = [
  { id: 'list', label: 'List', icon: 'view_list' },
  { id: 'grid', label: 'Grid', icon: 'grid_view' },
  { id: 'graph', label: 'Graph', icon: 'account_tree' },
]

export function ViewToggle({ activeView, onViewChange }: ViewToggleProps) {
  return (
    <div className="flex items-center gap-0.5 p-1 rounded-lg bg-user-message border border-border-subtle w-fit">
      {views.map(({ id, label, icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => onViewChange(id)}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors',
            activeView === id
              ? 'bg-primary/20 text-primary'
              : 'text-text-muted hover:text-text-light hover:bg-white/5'
          )}
        >
          <span className="material-symbols-outlined !text-base">{icon}</span>
          {label}
        </button>
      ))}
    </div>
  )
}
