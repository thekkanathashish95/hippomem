import { useCallback, useEffect, useState } from 'react'
import { api } from '@/services/api'
import type { EntityNode } from '@/types/memory'
import { useChatStore } from '@/stores/chatStore'
import { formatDate } from '@/utils/formatDate'
import { RefreshButton } from '@/components/common/RefreshButton'

const TYPE_LABELS: Record<string, string> = {
  person: 'People',
  pet: 'Pets',
  organization: 'Organizations',
  place: 'Places',
  project: 'Projects',
  tool: 'Tools',
  other: 'Other',
}

const TYPE_ICONS: Record<string, string> = {
  person: 'person',
  pet: 'pets',
  organization: 'corporate_fare',
  place: 'location_on',
  project: 'folder',
  tool: 'build',
  other: 'category',
}

const TYPE_ORDER = ['person', 'pet', 'organization', 'place', 'project', 'tool', 'other']


function FactList({ facts, pending = false }: { facts: string[]; pending?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const hasMore = facts.length > 3
  const visible = expanded ? facts : facts.slice(0, 3)

  return (
    <div>
      {pending && (
        <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-500/70 mb-1">Pending</p>
      )}
      <ul className={`space-y-1 pl-3 border-l-2 ${pending ? 'border-amber-500/30' : 'border-border-subtle'}`}>
        {visible.map((fact, i) => (
          <li key={i} className={`text-[12px] leading-snug ${pending ? 'text-text-muted' : 'text-text-light'}`}>
            {fact}
          </li>
        ))}
      </ul>
      {hasMore && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-[11px] text-primary hover:underline mt-1 ml-3"
        >
          {expanded ? 'Show less' : `+${facts.length - 3} more`}
        </button>
      )}
    </div>
  )
}

function EntityCard({ entity }: { entity: EntityNode }) {
  return (
    <div className="rounded-lg border border-border-subtle p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[13px] font-medium text-text-light truncate">{entity.canonical_name}</p>
        <span className="text-[11px] text-text-muted flex-shrink-0 px-1.5 py-0.5 rounded bg-border-subtle">
          {entity.reinforcement_count}×
        </span>
      </div>

      {entity.summary_text && (
        <p className="text-[12px] text-text-muted leading-relaxed">{entity.summary_text}</p>
      )}

      {entity.facts.length > 0 && <FactList facts={entity.facts} />}
      {entity.pending_facts.length > 0 && <FactList facts={entity.pending_facts} pending />}

      {entity.facts.length === 0 && entity.pending_facts.length === 0 && (
        <p className="text-[11px] text-text-muted italic">No facts yet.</p>
      )}

      <div className="text-[10px] text-text-muted flex gap-3 pt-0.5">
        <span>First: {formatDate(entity.created_at)}</span>
        <span>Last: {formatDate(entity.updated_at)}</span>
      </div>
    </div>
  )
}

export function PersonaView() {
  const { userId } = useChatStore()
  const [entities, setEntities] = useState<EntityNode[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!userId) return
    setLoading(true)
    api.getEntities(userId)
      .then((res) => {
        setEntities(res.entities)
        setError(null)
      })
      .catch(() => setError('Failed to load entities.'))
      .finally(() => setLoading(false))
  }, [userId])

  useEffect(() => { load() }, [load])

  const grouped = TYPE_ORDER.reduce<Record<string, EntityNode[]>>((acc, type) => {
    const items = entities.filter((e) => e.entity_type === type)
    if (items.length > 0) acc[type] = items
    return acc
  }, {})

  // catch any types not in TYPE_ORDER
  const otherTypes = entities
    .map((e) => e.entity_type)
    .filter((t) => !TYPE_ORDER.includes(t))
  const uniqueOther = [...new Set(otherTypes)]
  uniqueOther.forEach((t) => {
    const items = entities.filter((e) => e.entity_type === t)
    if (items.length > 0) grouped[t] = items
  })

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-6 py-4 border-b border-border-subtle flex-shrink-0 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-text-light">Entities</h2>
          <p className="text-[12px] text-text-muted mt-0.5">
            People, places, and things hippomem has learned about
          </p>
        </div>
        <RefreshButton onClick={load} isLoading={loading} />
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : error ? (
          <p className="text-sm text-red-400">{error}</p>
        ) : entities.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <span className="material-symbols-outlined text-4xl text-text-muted mb-3">group</span>
            <p className="text-sm text-text-muted">No entities learned yet.</p>
            <p className="text-[12px] text-text-muted mt-1">
              Mention people, places, or organizations in chat to build persona memory.
            </p>
          </div>
        ) : (
          <div className="space-y-8">
            {Object.entries(grouped).map(([type, items]) => (
              <div key={type}>
                <div className="flex items-center gap-2 mb-3">
                  <span className="material-symbols-outlined !text-base text-text-muted">
                    {TYPE_ICONS[type] ?? 'category'}
                  </span>
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    {TYPE_LABELS[type] ?? type}
                  </h3>
                  <span className="text-[10px] text-text-muted">({items.length})</span>
                </div>
                <div className="space-y-2">
                  {items.map((entity) => (
                    <EntityCard key={entity.id} entity={entity} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
