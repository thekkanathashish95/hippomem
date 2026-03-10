import { useEffect, useState } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { ConnectionSection } from './ConnectionSection'
import { FeaturesSection } from './FeaturesSection'
import { AdvancedSection } from './AdvancedSection'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'

export function SettingsView() {
  const { config, isLoading, isSaving, error, fetchConfig, saveConfig, isDirty } = useSettingsStore()

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  const [savedFeedback, setSavedFeedback] = useState(false)
  const handleSave = async () => {
    const ok = await saveConfig()
    if (ok) {
      setSavedFeedback(true)
      setTimeout(() => setSavedFeedback(false), 2000)
    }
  }

  const weightSum =
    (config?.retrieval_semantic_weight ?? 0) +
    (config?.retrieval_relevance_weight ?? 0) +
    (config?.retrieval_recency_weight ?? 0)
  const weightsValid = Math.abs(weightSum - 1) < 0.001
  const canSave = isDirty() && weightsValid && !savedFeedback

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto custom-scrollbar">
      <div className="max-w-2xl mx-auto p-6 space-y-8">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-text-light">Settings</h2>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave && !savedFeedback}
            className={`px-4 py-2 rounded-lg text-[13px] font-medium transition-all ${
              savedFeedback
                ? 'bg-green-600 text-white'
                : canSave
                  ? 'bg-primary text-white hover:bg-primary/90'
                  : 'bg-white/10 text-text-muted cursor-not-allowed'
            }`}
          >
            {isSaving ? 'Saving...' : savedFeedback ? 'Saved ✓' : 'Save'}
          </button>
        </div>

        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-[13px]">
            {error}
          </div>
        )}

        {!weightsValid && (
          <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[13px]">
            Retrieval weights must sum to 1.0. Current sum: {weightSum.toFixed(2)}
          </div>
        )}

        <ConnectionSection />
        <FeaturesSection />
        <AdvancedSection />
      </div>
    </div>
  )
}
