import { useCallback, useEffect, useState } from 'react'
import { api } from '@/services/api'
import type { SelfTrait, Persona } from '@/types/memory'
import { useChatStore } from '@/stores/chatStore'
import { formatDate } from '@/utils/formatDate'
import { RefreshButton } from '@/components/common/RefreshButton'

const CATEGORY_LABELS: Record<string, string> = {
  stable_attribute: 'Stable Attributes',
  goal: 'Goals',
  personality: 'Personality',
  preference: 'Preferences',
  constraint: 'Constraints',
  project: 'Projects',
  social: 'Social',
}

const CATEGORY_ORDER = ['stable_attribute', 'goal', 'personality', 'preference', 'constraint', 'project', 'social']

export function SelfMemoryView() {
  const { userId } = useChatStore()
  const [traits, setTraits] = useState<SelfTrait[]>([])
  const [persona, setPersona] = useState<Persona | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!userId) return
    setLoading(true)
    api.getSelfTraits(userId)
      .then((res) => {
        setTraits(res.traits)
        setPersona(res.persona ?? null)
        setError(null)
      })
      .catch(() => setError('Failed to load self traits.'))
      .finally(() => setLoading(false))
  }, [userId])

  useEffect(() => { load() }, [load])

  const grouped = CATEGORY_ORDER.reduce<Record<string, SelfTrait[]>>((acc, cat) => {
    const items = traits.filter((t) => t.category === cat)
    if (items.length > 0) acc[cat] = items
    return acc
  }, {})

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-6 py-4 border-b border-border-subtle flex-shrink-0 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-text-light">Self Memory</h2>
          <p className="text-[12px] text-text-muted mt-0.5">What hippomem has learned about you</p>
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
        ) : traits.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <span className="material-symbols-outlined text-4xl text-text-muted mb-3">person</span>
            <p className="text-sm text-text-muted">No self traits learned yet.</p>
            <p className="text-[12px] text-text-muted mt-1">Chat more to build your self profile.</p>
          </div>
        ) : (
          <div className="space-y-8">
            {/* Persona narrative */}
            {persona && (
              <div className="rounded-lg border border-primary/30 bg-primary/5 p-4">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-primary">
                    Persona
                  </h3>
                  <span className="text-[10px] text-text-muted">
                    Last synthesized: {formatDate(persona.updated_at)}
                  </span>
                </div>
                <p className="text-[13px] text-text-light leading-relaxed whitespace-pre-wrap">
                  {persona.summary_text}
                </p>
              </div>
            )}

            {Object.entries(grouped).map(([cat, items]) => {
              const active = items.filter((t) => t.is_active)
              const pending = items.filter((t) => !t.is_active)
              return (
                <div key={cat}>
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted mb-3">
                    {CATEGORY_LABELS[cat] ?? cat}
                  </h3>
                  <div className="space-y-2">
                    {[...active, ...pending].map((trait) => (
                      <div
                        key={`${trait.category}:${trait.key}`}
                        className={`rounded-lg border border-border-subtle p-3 ${trait.is_active ? '' : 'opacity-50'}`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-[12px] font-medium text-text-muted">{trait.key}</span>
                              {!trait.is_active && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-border-subtle text-text-muted">
                                  unconfirmed
                                </span>
                              )}
                            </div>
                            <p className="text-[13px] text-text-light mt-0.5">{trait.value}</p>
                            {trait.previous_value && (
                              <p className="text-[11px] text-text-muted mt-0.5 line-through">
                                {trait.previous_value}
                              </p>
                            )}
                          </div>
                          <span className="text-[11px] text-text-muted flex-shrink-0 px-1.5 py-0.5 rounded bg-border-subtle">
                            {trait.evidence_count}×
                          </span>
                        </div>
                        <div className="text-[10px] text-text-muted mt-2 flex gap-3">
                          <span>First: {formatDate(trait.first_observed_at)}</span>
                          <span>Last: {formatDate(trait.last_observed_at)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
