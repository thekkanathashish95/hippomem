import type { MemoryNode } from '@/types/memory'
import { cn } from '@/lib/utils'
import { formatDateTime as formatDate } from '@/utils/formatDate'

interface GridViewProps {
  nodes: MemoryNode[]
  onSelectEvent: (eventId: string) => void
}

export function GridView({ nodes, onSelectEvent }: GridViewProps) {
  const sorted = [...nodes].sort((a, b) => (b.relevance_score ?? 0) - (a.relevance_score ?? 0))

  return (
    <div className="p-5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 overflow-auto">
      {sorted.map((node) => (
        <button
          key={node.id}
          type="button"
          onClick={() => onSelectEvent(node.id)}
          className="text-left p-4 rounded-xl bg-user-message border border-border-subtle hover:border-primary/40 hover:bg-primary/5 transition-all cursor-pointer"
        >
          <p className="text-[13px] text-text-light line-clamp-2 mb-2">
            {node.core_intent || '—'}
          </p>
          <div className="flex items-center gap-2 mb-2">
            <span
              className={cn(
                'inline-block px-2 py-0.5 rounded text-[11px] font-medium',
                node.event_kind === 'summary' && 'bg-[#8b5cf6]/20 text-[#8b5cf6]',
                node.event_kind === 'episode' && 'bg-primary/20 text-primary',
                node.event_kind === 'entity' && 'bg-amber-500/20 text-amber-400'
              )}
            >
              {node.event_kind}
            </span>
          </div>
          <div className="flex items-center gap-3 text-[11px] text-text-muted">
            <span className="flex items-center gap-1">
              <span className="w-8 h-1 bg-border-subtle rounded overflow-hidden">
                <span
                  className="block h-full bg-primary rounded"
                  style={{ width: `${(node.relevance_score ?? 0) * 100}%` }}
                />
              </span>
              {(node.relevance_score ?? 0).toFixed(0)}%
            </span>
            <span>{formatDate(node.created_at)}</span>
          </div>
        </button>
      ))}
    </div>
  )
}
