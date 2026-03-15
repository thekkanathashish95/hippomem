import type { EventDetail } from '@/types/memory'
import { useMemoryStore } from '@/stores/memoryStore'
import { cn } from '@/lib/utils'
import { formatDateTime } from '@/utils/formatDate'

interface EventDetailPanelProps {
  event: EventDetail | null
  isLoading: boolean
  onClose: () => void
}

export function EventDetailPanel({ event, isLoading, onClose }: EventDetailPanelProps) {
  const { nodes } = useMemoryStore()

  const nodeMap = new Map(nodes.map((n) => [n.id, n]))

  if (!event && !isLoading) return null

  return (
    <div
      className={cn(
        'w-[380px] flex-shrink-0 border-l border-border-subtle bg-dark-sidebar flex flex-col overflow-hidden',
        'panel-slide-in'
      )}
    >
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3 flex-shrink-0">
        <h3 className="font-semibold text-sm text-text-light">Event Detail</h3>
        <button
          type="button"
          onClick={onClose}
          className="p-1.5 rounded-md text-text-muted hover:text-white hover:bg-white/10 transition-colors"
        >
          <span className="material-symbols-outlined !text-lg">close</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : event ? (
          <div className="space-y-4">
            {/* Header */}
            <div>
              <p className="text-[13px] text-text-light leading-relaxed mb-2">
                {event.core_intent || '—'}
              </p>
              <span
                className={cn(
                  'inline-block px-2 py-0.5 rounded text-[11px] font-medium',
                  event.event_kind === 'summary' && 'bg-[#8b5cf6]/20 text-[#8b5cf6]',
                  event.event_kind === 'episode' && 'bg-primary/20 text-primary',
                  event.event_kind === 'entity' && 'bg-amber-500/20 text-amber-400'
                )}
              >
                {event.event_kind}
              </span>
            </div>

            {/* Status strip */}
            <div className="flex flex-wrap gap-2 items-center">
              {event.is_active && (
                <span className="px-2 py-0.5 rounded-full bg-primary/20 text-primary text-[11px] font-medium">
                  Active
                </span>
              )}
              {event.is_dormant && (
                <span className="px-2 py-0.5 rounded-full bg-[#4b5563]/30 text-[#9ca3af] text-[11px] font-medium">
                  Dormant
                </span>
              )}
              <span className="text-[11px] text-text-muted">
                Relevance: {(event.relevance_score ?? 0).toFixed(2)}
              </span>
              <span className="text-[11px] text-text-muted">
                Reinforcements: {event.reinforcement_count ?? 0}
              </span>
            </div>
            <div className="w-full h-1.5 bg-border-subtle rounded overflow-hidden">
              <div
                className="h-full bg-primary rounded"
                style={{ width: `${(event.relevance_score ?? 0) * 100}%` }}
              />
            </div>

            {/* Summary (post-consolidation) */}
            {event.summary_text && (
              <div className="rounded-md bg-primary/5 border border-primary/20 px-3 py-2">
                <h4 className="text-[10px] font-semibold uppercase tracking-wider text-primary mb-1.5">
                  Summary
                </h4>
                <p className="text-[12px] text-text-light leading-relaxed">{event.summary_text}</p>
              </div>
            )}

            {/* Consolidated updates / entity facts */}
            {event.updates && event.updates.length > 0 && (
              <div>
                <h4 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted mb-2">
                  {event.event_kind === 'entity' ? 'Facts' : 'Updates'}
                </h4>
                <ul className="space-y-1.5 pl-4 border-l-2 border-border-subtle">
                  {event.updates.map((u, i) => (
                    <li key={i} className="text-[12px] text-text-light">{u}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Pending updates (since last consolidation) */}
            {event.pending_facts && event.pending_facts.length > 0 && (
              <div>
                <h4 className="text-[11px] font-semibold uppercase tracking-wider text-amber-500/70 mb-2">
                  Pending
                </h4>
                <ul className="space-y-1.5 pl-4 border-l-2 border-amber-500/30">
                  {event.pending_facts.map((u, i) => (
                    <li key={i} className="text-[12px] text-text-muted">{u}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Timestamps */}
            <div className="text-[11px] text-text-muted space-y-1">
              <p>Created: {formatDateTime(event.created_at)}</p>
              <p>Last updated: {formatDateTime(event.last_updated_at)}</p>
            </div>

            {/* Connected memories */}
            {event.edges && event.edges.length > 0 && (
              <div>
                <h4 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted mb-2">
                  Connected Memories
                </h4>
                <ul className="space-y-1.5">
                  {event.edges.map((e) => {
                    const neighbor = nodeMap.get(e.neighbor_id)
                    const intent = neighbor?.core_intent ?? '—'
                    return (
                      <li
                        key={e.neighbor_id}
                        className="text-[12px] text-text-light truncate"
                        title={intent}
                      >
                        <span className="text-text-muted text-[11px]">
                          {Math.min(1, e.weight).toFixed(2)}
                        </span>{' '}
                        {intent}
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}
