import { useState, useCallback, useEffect } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { api } from '@/services/api'
import { FieldWithTooltip } from './FieldWithTooltip'

const MASKED_KEY = 'sk-****'

const TOOLTIPS = {
  llm_api_key:
    'Your OpenAI-compatible API key. Used by hippomem for all internal memory operations (not for your chat model unless they share a key). Never shown after saving.',
  llm_base_url:
    'Base URL of your LLM provider. Default is OpenAI. Use https://openrouter.ai/api/v1 for OpenRouter, or any OpenAI-compatible endpoint.',
  llm_model:
    'Model used internally by hippomem for extraction, synthesis, and retrieval decisions. A fast, cheap model works well here — this is not your chat model.',
  chat_model:
    'Model used to generate chat responses in the Studio. Can be the same as or different from the memory model.',
  system_prompt:
    'Base system prompt prepended before memory context. Memory context is appended automatically — no need to mention it here.',
} as const

export function ConnectionSection() {
  const { config, updateField } = useSettingsStore()
  const [apiKeyFocused, setApiKeyFocused] = useState(false)
  const [modelsValid, setModelsValid] = useState<boolean | null>(null)
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [availableModels, setAvailableModels] = useState<{ id: string; name: string }[]>([])

  const showFetchModels = config?.llm_base_url?.includes('openrouter.ai') ?? false

  // Fetch models on mount when OpenRouter (uses stored key server-side)
  useEffect(() => {
    if (!showFetchModels) return
    setModelsLoading(true)
    api
      .getConfigModels()
      .then((res) => {
        setModelsValid(res.valid)
        setModelsError(res.error ?? null)
        setAvailableModels(res.models ?? [])
      })
      .catch(() => {
        setModelsValid(false)
        setModelsError('Failed to fetch models')
      })
      .finally(() => setModelsLoading(false))
  }, [showFetchModels, config?.llm_base_url])

  const validateApiKey = useCallback(
    async (key: string, baseUrl?: string) => {
      if (!key || key === MASKED_KEY) return
      setModelsLoading(true)
      setModelsValid(null)
      setModelsError(null)
      try {
        const res = await api.getConfigModels(key, baseUrl)
        setModelsValid(res.valid)
        setModelsError(res.error ?? null)
        setAvailableModels(res.models ?? [])
      } catch {
        setModelsValid(false)
        setModelsError('Failed to fetch models')
      } finally {
        setModelsLoading(false)
      }
    },
    []
  )

  const handleApiKeyBlur = () => {
    const val = config?.llm_api_key ?? ''
    if (val && val !== MASKED_KEY) {
      validateApiKey(val, config?.llm_base_url)
    } else {
      setApiKeyFocused(false)
      if (!val && config) {
        updateField('llm_api_key', MASKED_KEY)
      }
    }
  }

  const handleApiKeyFocus = () => {
    setApiKeyFocused(true)
    if (config?.llm_api_key === MASKED_KEY) {
      updateField('llm_api_key', '')
    }
  }

  if (!config) return null

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-text-light uppercase tracking-wider">
        Connection
      </h3>
      <div className="space-y-4">
        <FieldWithTooltip label="API Base URL" tooltip={TOOLTIPS.llm_base_url}>
          <input
            type="text"
            value={config.llm_base_url}
            onChange={(e) => updateField('llm_base_url', e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary"
            placeholder="https://openrouter.ai/api/v1"
          />
        </FieldWithTooltip>

        <FieldWithTooltip label="API Key" tooltip={TOOLTIPS.llm_api_key}>
          <div className="relative">
            <input
              type="password"
              value={apiKeyFocused ? config.llm_api_key : (config.llm_api_key || MASKED_KEY)}
              onChange={(e) => updateField('llm_api_key', e.target.value)}
              onFocus={handleApiKeyFocus}
              onBlur={handleApiKeyBlur}
              placeholder={MASKED_KEY}
              className="w-full px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary"
            />
            {modelsLoading && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2">
                <span className="material-symbols-outlined !text-base animate-spin text-text-muted">
                  progress_activity
                </span>
              </span>
            )}
            {!modelsLoading && modelsValid === true && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-green-500">
                <span className="material-symbols-outlined !text-base">check_circle</span>
              </span>
            )}
            {!modelsLoading && modelsValid === false && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-red-500" title={modelsError ?? ''}>
                <span className="material-symbols-outlined !text-base">cancel</span>
              </span>
            )}
          </div>
          {modelsError && modelsValid === false && (
            <p className="text-[12px] text-red-500 mt-1">
              {modelsError}
              {modelsError === 'Invalid API key' && ' — double-check your API Base URL is set correctly.'}
            </p>
          )}
          <p className="text-[12px] text-text-muted mt-1">
            This key is stored locally and only used to make API requests from hippomem.
          </p>
        </FieldWithTooltip>

        <FieldWithTooltip label="Memory Model" tooltip={TOOLTIPS.llm_model}>
          <div className="flex gap-2">
            {showFetchModels && (
              <select
                value={config.llm_model}
                onChange={(e) => updateField('llm_model', e.target.value)}
                className="flex-1 px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {availableModels.length > 0 ? (
                  availableModels.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))
                ) : (
                  <option value={config.llm_model}>{config.llm_model}</option>
                )}
              </select>
            )}
            {!showFetchModels && (
              <input
                type="text"
                value={config.llm_model}
                onChange={(e) => updateField('llm_model', e.target.value)}
                className="flex-1 px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="x-ai/grok-4.1-fast"
              />
            )}
          </div>
        </FieldWithTooltip>

        <FieldWithTooltip label="Chat Model" tooltip={TOOLTIPS.chat_model}>
          <div className="flex gap-2">
            {showFetchModels && (
              <select
                value={config.chat_model}
                onChange={(e) => updateField('chat_model', e.target.value)}
                className="flex-1 px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {availableModels.length > 0 ? (
                  availableModels.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))
                ) : (
                  <option value={config.chat_model}>{config.chat_model}</option>
                )}
              </select>
            )}
            {!showFetchModels && (
              <input
                type="text"
                value={config.chat_model}
                onChange={(e) => updateField('chat_model', e.target.value)}
                className="flex-1 px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="x-ai/grok-4.1-fast"
              />
            )}
          </div>
        </FieldWithTooltip>

        <FieldWithTooltip label="System Prompt" tooltip={TOOLTIPS.system_prompt}>
          <textarea
            value={config.system_prompt}
            onChange={(e) => updateField('system_prompt', e.target.value)}
            rows={4}
            className="w-full px-3 py-2 rounded-lg bg-user-message border border-border-subtle text-text-light text-[13px] focus:outline-none focus:ring-1 focus:ring-primary resize-y min-h-[80px]"
            placeholder="You are a helpful assistant..."
          />
        </FieldWithTooltip>
      </div>
    </section>
  )
}
