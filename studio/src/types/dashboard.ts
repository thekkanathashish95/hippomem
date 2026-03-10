export interface DashboardStats {
  memory: {
    total_engrams: number
    episodes: number
    summaries: number
    entities: number
    personas: number
    active: number
    dormant: number
  }
  usage: {
    total_interactions: number
    total_input_tokens: number
    total_output_tokens: number
    total_tokens: number
    total_cost: number
  }
}
