import { useSettingsStore } from '@/stores/settingsStore'
import { FieldWithTooltip } from './FieldWithTooltip'

const TOOLTIPS = {
  enable_background_consolidation:
    'Periodically runs memory decay and demotion in the background. Keeps memory healthy without manual calls to /consolidate. Runs every N hours (configurable in Advanced).',
  enable_clustering:
    'Groups related episodic events into named summaries during consolidation cycles. Reduces memory clutter over long conversations. Requires Background Consolidation to be on.',
  enable_entity_extraction:
    'Tracks named entities — people, organizations, projects, pets — across conversations. Builds persistent profiles that evolve over time.',
  enable_self_memory:
    "Extracts durable signals about the user's personality, goals, and preferences. Builds a persona snapshot that persists across all sessions.",
} as const

export function FeaturesSection() {
  const { config, updateField } = useSettingsStore()

  if (!config) return null

  const bgConsolidationOff = !config.enable_background_consolidation

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-text-light uppercase tracking-wider">
        Features
      </h3>
      <div className="space-y-4">
        <FieldWithTooltip
          label="Background Consolidation"
          tooltip={TOOLTIPS.enable_background_consolidation}
        >
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={config.enable_background_consolidation}
              onChange={(e) => updateField('enable_background_consolidation', e.target.checked)}
              className="w-4 h-4 rounded border-border-subtle bg-user-message text-primary focus:ring-primary"
            />
            <span className="text-[13px] text-text-light">Enabled</span>
          </label>
        </FieldWithTooltip>

        <FieldWithTooltip
          label="Memory Clustering"
          tooltip={TOOLTIPS.enable_clustering}
        >
          <label className={`flex items-center gap-2 ${bgConsolidationOff ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
            <input
              type="checkbox"
              checked={config.enable_clustering}
              onChange={(e) => updateField('enable_clustering', e.target.checked)}
              disabled={bgConsolidationOff}
              className="w-4 h-4 rounded border-border-subtle bg-user-message text-primary focus:ring-primary"
            />
            <span className="text-[13px] text-text-light">Enabled</span>
          </label>
        </FieldWithTooltip>

        <FieldWithTooltip
          label="Entity Memory (v1.5)"
          tooltip={TOOLTIPS.enable_entity_extraction}
        >
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={config.enable_entity_extraction}
              onChange={(e) => updateField('enable_entity_extraction', e.target.checked)}
              className="w-4 h-4 rounded border-border-subtle bg-user-message text-primary focus:ring-primary"
            />
            <span className="text-[13px] text-text-light">Enabled</span>
          </label>
        </FieldWithTooltip>

        <FieldWithTooltip
          label="Self Memory (v1.6)"
          tooltip={TOOLTIPS.enable_self_memory}
        >
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={config.enable_self_memory}
              onChange={(e) => updateField('enable_self_memory', e.target.checked)}
              className="w-4 h-4 rounded border-border-subtle bg-user-message text-primary focus:ring-primary"
            />
            <span className="text-[13px] text-text-light">Enabled</span>
          </label>
        </FieldWithTooltip>
      </div>
    </section>
  )
}
