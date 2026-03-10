export interface MemoryNode {
  id: string
  core_intent: string
  event_kind: 'episode' | 'summary' | 'entity'
  relevance_score: number
  is_active: boolean
  is_dormant: boolean
  reinforcement_count: number
  created_at: string
  updated_at: string
}

export interface MemoryEdge {
  source: string
  target: string
  weight: number
  /** When present, use for styling (e.g. "mention" = episode→entity). */
  link_kind?: string
}

export interface GraphResponse {
  nodes: MemoryNode[]
  edges: MemoryEdge[]
}

export interface EventDetailNeighbor {
  neighbor_id: string
  weight: number
}

export interface EventDetail {
  id: string
  core_intent: string
  event_kind: 'episode' | 'summary' | 'entity'
  updates: string[]
  summary_text: string | null
  relevance_score: number
  reinforcement_count: number
  is_active: boolean
  is_dormant: boolean
  created_at: string
  updated_at: string
  last_updated_at: string
  edges: EventDetailNeighbor[]
}

export interface SelfTrait {
  category: string
  key: string
  value: string
  previous_value: string | null
  confidence_score: number
  evidence_count: number
  is_active: boolean
  first_observed_at: string
  last_observed_at: string
}

export interface SelfTraitsResponse {
  traits: SelfTrait[]
}

export interface EntityNode {
  id: string
  canonical_name: string
  entity_type: string
  facts: string[]
  summary_text: string | null
  reinforcement_count: number
  created_at: string
  updated_at: string
}

export interface EntitiesResponse {
  entities: EntityNode[]
}
