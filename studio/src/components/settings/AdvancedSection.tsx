import { useState } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { FieldWithTooltip } from './FieldWithTooltip'

const DEFAULTS = {
  max_active_events: 5,
  max_dormant_events: 5,
  ephemeral_trace_capacity: 8,
  continuation_threshold: 0.7,
  local_scan_threshold: 0.6,
  retrieval_semantic_weight: 0.5,
  retrieval_relevance_weight: 0.3,
  retrieval_recency_weight: 0.2,
  decay_rate_per_hour: 0.98,
  consolidation_interval_hours: 1.0,
} as const

const TOOLTIPS = {
  max_active_events:
    'Maximum episodic events held in working memory per user. Analogous to human working memory. Higher values = richer context but more LLM tokens per retrieval.',
  max_dormant_events:
    'Recently demoted events kept available for deep retrieval (C3). Acts as a short-term buffer before events are fully archived.',
  ephemeral_trace_capacity:
    'Weak short-term traces captured before a full episodic event is formed. FIFO eviction when full. Increase for fast-paced conversations.',
  continuation_threshold:
    'If C1 (continuation check) confidence exceeds this, hippomem assumes the conversation is ongoing and skips deep retrieval (C3). Higher = more skipping = fewer LLM calls but may miss context shifts.',
  local_scan_threshold:
    'If C2 (local scan) score exceeds this, the result is used directly without escalating to C3 semantic search. Higher = faster but may miss long-term memories.',
  retrieval_semantic_weight:
    'Weight of vector similarity in C2 scoring. Higher = memories that are semantically closer to the current message score higher. Must sum to 1.0 with the other two weights.',
  retrieval_relevance_weight:
    'Weight of LLM-assigned relevance score in C2 scoring. Higher = memories the LLM judged as directly relevant score higher.',
  retrieval_recency_weight:
    'Weight of recency in C2 scoring. Higher = more recently accessed memories are preferred.',
  decay_rate_per_hour:
    'Relevance multiplier applied per hour of inactivity. 0.98 ≈ 2% decay per hour ≈ 40% loss per day. Lower values = faster forgetting. Higher values = memories persist longer.',
  consolidation_interval_hours:
    'How often (in hours) the background consolidation cycle runs. Only relevant if Background Consolidation is enabled.',
} as const

function countNonDefaults(config: Record<string, unknown>): number {
  let n = 0
  for (const [k, def] of Object.entries(DEFAULTS)) {
    if (config[k] !== undefined && config[k] !== def) n++
  }
  return n
}

export function AdvancedSection() {
  const { config, updateField } = useSettingsStore()
  const [expanded, setExpanded] = useState(false)

  if (!config) return null

  const customizedCount = countNonDefaults(config as unknown as Record<string, unknown>)
  const weightSum =
    (config.retrieval_semantic_weight ?? 0) +
    (config.retrieval_relevance_weight ?? 0) +
    (config.retrieval_recency_weight ?? 0)
  const weightsValid = Math.abs(weightSum - 1) < 0.001
  const bgConsolidationOff = !config.enable_background_consolidation

  const LABELS: Record<string, string> = {
    continuation_threshold: 'Continuation Confidence (C1)',
    local_scan_threshold: 'Local Scan Confidence (C2)',
    retrieval_semantic_weight: 'Semantic Weight',
    retrieval_relevance_weight: 'Relevance Weight',
    retrieval_recency_weight: 'Recency Weight',
    decay_rate_per_hour: 'Decay Rate (per hour)',
  }

  const SliderField = ({
    field,
    label,
    min,
    max,
    step = 0.01,
    tooltip,
  }: {
    field: keyof typeof TOOLTIPS
    label: string
    min: number
    max: number
    step?: number
    tooltip: string
  }) => (
    <FieldWithTooltip label={label} tooltip={tooltip}>
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={config[field] as number}
          onChange={(e) => updateField(field, parseFloat(e.target.value) as never)}
          className="flex-1 h-2 rounded-lg appearance-none bg-user-message accent-primary"
        />
        <span className="text-[13px] text-text-muted w-12 text-right">
          {(config[field] as number).toFixed(2)}
        </span>
      </div>
    </FieldWithTooltip>
  )

  const content = (
    <div className="space-y-6 pt-2">
      <div>
        <h4 className="text-[12px] font-medium text-text-muted uppercase tracking-wider mb-3">
          Memory Capacity
        </h4>
        <div className="space-y-4">
          <FieldWithTooltip label="Active Memory Slots" tooltip={TOOLTIPS.max_active_events}>
            <input
              type="number"
              min={1}
              max={20}
              value={config.max_active_events}
              onChange={(e) => updateField('max_active_events', parseInt(e.target.value, 10) || 5)}
              className="w-full px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </FieldWithTooltip>
          <FieldWithTooltip label="Dormant Memory Slots" tooltip={TOOLTIPS.max_dormant_events}>
            <input
              type="number"
              min={1}
              max={20}
              value={config.max_dormant_events}
              onChange={(e) => updateField('max_dormant_events', parseInt(e.target.value, 10) || 5)}
              className="w-full px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </FieldWithTooltip>
          <FieldWithTooltip label="Ephemeral Trace Slots" tooltip={TOOLTIPS.ephemeral_trace_capacity}>
            <input
              type="number"
              min={1}
              max={20}
              value={config.ephemeral_trace_capacity}
              onChange={(e) =>
                updateField('ephemeral_trace_capacity', parseInt(e.target.value, 10) || 8)
              }
              className="w-full px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </FieldWithTooltip>
        </div>
      </div>

      <div>
        <h4 className="text-[12px] font-medium text-text-muted uppercase tracking-wider mb-3">
          Retrieval Cascade
        </h4>
        <div className="space-y-4">
          <SliderField
            field="continuation_threshold"
            label={LABELS.continuation_threshold}
            min={0}
            max={1}
            tooltip={TOOLTIPS.continuation_threshold}
          />
          <SliderField
            field="local_scan_threshold"
            label={LABELS.local_scan_threshold}
            min={0}
            max={1}
            tooltip={TOOLTIPS.local_scan_threshold}
          />
          <SliderField
            field="retrieval_semantic_weight"
            label={LABELS.retrieval_semantic_weight}
            min={0}
            max={1}
            tooltip={TOOLTIPS.retrieval_semantic_weight}
          />
          <SliderField
            field="retrieval_relevance_weight"
            label={LABELS.retrieval_relevance_weight}
            min={0}
            max={1}
            tooltip={TOOLTIPS.retrieval_relevance_weight}
          />
          <SliderField
            field="retrieval_recency_weight"
            label={LABELS.retrieval_recency_weight}
            min={0}
            max={1}
            tooltip={TOOLTIPS.retrieval_recency_weight}
          />
          <div className="flex items-center gap-2">
            <span className="text-[12px] text-text-muted">Weight sum:</span>
            <span
              className={`text-[12px] font-medium ${weightsValid ? 'text-green-500' : 'text-red-500'}`}
            >
              {weightSum.toFixed(2)} {weightsValid ? '✓' : '(must be 1.0)'}
            </span>
          </div>
        </div>
      </div>

      <div>
        <h4 className="text-[12px] font-medium text-text-muted uppercase tracking-wider mb-3">
          Memory Decay
        </h4>
        <div className="space-y-4">
          <SliderField
            field="decay_rate_per_hour"
            label={LABELS.decay_rate_per_hour}
            min={0.9}
            max={1}
            tooltip={TOOLTIPS.decay_rate_per_hour}
          />
          <FieldWithTooltip
            label="Consolidation Interval (hours)"
            tooltip={TOOLTIPS.consolidation_interval_hours}
          >
            <input
              type="number"
              min={0.5}
              max={24}
              step={0.5}
              value={config.consolidation_interval_hours}
              onChange={(e) =>
                updateField('consolidation_interval_hours', parseFloat(e.target.value) || 1)
              }
              disabled={bgConsolidationOff}
              className={`w-full px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary ${
                bgConsolidationOff ? 'opacity-50 cursor-not-allowed' : ''
              }`}
            />
          </FieldWithTooltip>
        </div>
      </div>

      {config.max_dormant_events < config.max_active_events && (
        <p className="text-[12px] text-amber-500">
          Dormant slots are fewer than active slots — demoted events will evict quickly.
        </p>
      )}
      {config.continuation_threshold > 0.85 &&
        config.local_scan_threshold > 0.85 && (
          <p className="text-[12px] text-amber-500">
            C3 deep retrieval will rarely fire — long-term memories may be missed.
          </p>
        )}
    </div>
  )

  return (
    <section className="space-y-2">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left py-2 text-sm font-semibold text-text-light uppercase tracking-wider hover:text-primary transition-colors"
      >
        <span
          className={`material-symbols-outlined !text-base transition-transform ${expanded ? 'rotate-90' : ''}`}
        >
          chevron_right
        </span>
        Advanced {customizedCount > 0 ? `· ${customizedCount} customized` : ''}
      </button>
      {expanded && content}
    </section>
  )
}
