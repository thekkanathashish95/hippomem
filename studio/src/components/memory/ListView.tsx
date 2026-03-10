import type { MemoryNode } from '@/types/memory'
import { cn } from '@/lib/utils'
import { formatDateTime as formatDate } from '@/utils/formatDate'

interface ListViewProps {
  nodes: MemoryNode[]
  onSelectEvent: (eventId: string) => void
}

export function ListView({ nodes, onSelectEvent }: ListViewProps) {
  const sorted = [...nodes].sort((a, b) => (b.relevance_score ?? 0) - (a.relevance_score ?? 0))

  return (
    <div className="overflow-auto">
      <table className="w-full text-left border-collapse">
        <thead className="sticky top-0 bg-pure-black/95 backdrop-blur z-10">
          <tr className="border-b border-border-subtle">
            <th className="py-2 px-4 text-[11px] font-semibold uppercase tracking-wider text-text-muted w-8">
              Status
            </th>
            <th className="py-2 px-4 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Core Intent
            </th>
            <th className="py-2 px-4 text-[11px] font-semibold uppercase tracking-wider text-text-muted w-24">
              Kind
            </th>
            <th className="py-2 px-4 text-[11px] font-semibold uppercase tracking-wider text-text-muted w-20">
              Relevance
            </th>
            <th className="py-2 px-4 text-[11px] font-semibold uppercase tracking-wider text-text-muted w-24">
              Reinforce
            </th>
            <th className="py-2 px-4 text-[11px] font-semibold uppercase tracking-wider text-text-muted w-32">
              Created
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((node) => (
            <tr
              key={node.id}
              onClick={() => onSelectEvent(node.id)}
              className="border-b border-border-subtle/50 hover:bg-user-message/50 cursor-pointer transition-colors"
            >
              <td className="py-2.5 px-4">
                <div
                  className={cn(
                    'w-2 h-2 rounded-full',
                    node.is_active && 'bg-primary',
                    node.is_dormant && 'bg-[#4b5563] opacity-60',
                    !node.is_active && !node.is_dormant && 'bg-border-subtle opacity-40'
                  )}
                  title={node.is_active ? 'Active' : node.is_dormant ? 'Dormant' : 'Other'}
                />
              </td>
              <td className="py-2.5 px-4 text-[13px] text-text-light max-w-[320px] truncate">
                {node.core_intent || '—'}
              </td>
              <td className="py-2.5 px-4">
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
              </td>
              <td className="py-2.5 px-4 text-[12px] text-text-muted">
                {(node.relevance_score ?? 0).toFixed(2)}
              </td>
              <td className="py-2.5 px-4 text-[12px] text-text-muted">
                {node.reinforcement_count ?? 0}
              </td>
              <td className="py-2.5 px-4 text-[12px] text-text-muted">
                {formatDate(node.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
