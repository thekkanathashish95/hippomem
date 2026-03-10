/** Config as returned by GET /config (API key masked) */
export interface ConfigResponse {
  llm_api_key: string
  llm_base_url: string
  llm_model: string
  chat_model: string
  system_prompt: string
  embedding_model: string
  max_active_events: number
  max_dormant_events: number
  ephemeral_trace_capacity: number
  decay_rate_per_hour: number
  continuation_threshold: number
  local_scan_threshold: number
  retrieval_semantic_weight: number
  retrieval_relevance_weight: number
  retrieval_recency_weight: number
  enable_background_consolidation: boolean
  consolidation_interval_hours: number
  enable_clustering: boolean
  enable_entity_extraction: boolean
  enable_self_memory: boolean
}

/** Partial config for PATCH /config */
export type ConfigPatch = Partial<ConfigResponse>

/** Response from GET /config/models */
export interface ConfigModelsResponse {
  valid: boolean
  models?: { id: string; name: string }[]
  error?: string
}
