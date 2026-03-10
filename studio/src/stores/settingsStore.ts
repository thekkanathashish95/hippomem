import { create } from 'zustand'
import { api } from '@/services/api'
import type { ConfigResponse, ConfigPatch } from '@/types/settings'

const MASKED_KEY = 'sk-****'

function buildPatchPayload(
  original: ConfigResponse,
  current: ConfigResponse
): ConfigPatch {
  const patch: ConfigPatch = {}
  for (const key of Object.keys(current) as (keyof ConfigResponse)[]) {
    if (key === 'llm_api_key') {
      const val = current[key]
      if (val && val !== MASKED_KEY && !val.startsWith('sk-****')) {
        patch[key] = val
      }
    } else if (JSON.stringify(current[key]) !== JSON.stringify(original[key])) {
      ;(patch as Record<string, unknown>)[key] = current[key]
    }
  }
  return patch
}

interface SettingsStore {
  config: ConfigResponse | null
  original: ConfigResponse | null
  isLoading: boolean
  isSaving: boolean
  error: string | null
  fetchConfig: () => Promise<void>
  saveConfig: () => Promise<boolean>
  updateField: <K extends keyof ConfigResponse>(key: K, value: ConfigResponse[K]) => void
  isDirty: () => boolean
}

export const useSettingsStore = create<SettingsStore>((set, get) => ({
  config: null,
  original: null,
  isLoading: false,
  isSaving: false,
  error: null,

  fetchConfig: async () => {
    set({ isLoading: true, error: null })
    try {
      const data = await api.getConfig()
      set({ config: data, original: data, isLoading: false })
    } catch (err) {
      console.error('Failed to fetch config:', err)
      set({
        isLoading: false,
        error: 'Failed to load settings. Is the hippomem server running?',
      })
    }
  },

  saveConfig: async () => {
    const { config, original } = get()
    if (!config || !original) return false
    const patch = buildPatchPayload(original, config)
    if (Object.keys(patch).length === 0) return false

    set({ isSaving: true, error: null })
    try {
      const { config: updated } = await api.patchConfig(patch)
      set({ config: updated, original: updated, isSaving: false })
      return true
    } catch (err) {
      console.error('Failed to save config:', err)
      set({
        isSaving: false,
        error: err instanceof Error ? err.message : 'Failed to save settings',
      })
      return false
    }
  },

  updateField: (key, value) => {
    const { config } = get()
    if (!config) return
    set({ config: { ...config, [key]: value } })
  },

  isDirty: () => {
    const { config, original } = get()
    if (!config || !original) return false
    const patch = buildPatchPayload(original, config)
    return Object.keys(patch).length > 0
  },
}))
