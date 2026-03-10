export interface InteractionSummary {
  id: string
  user_id: string
  operation: 'decode' | 'encode' | 'consolidate'
  call_count: number
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  total_cost: number
  total_latency_ms: number
  created_at: string
  turn_id?: string
  session_id?: string
}

export interface InteractionStep {
  step_order: number
  op: string
  model: string
  messages: Array<{ role: string; content: string }>
  raw_response: string
  input_tokens: number
  output_tokens: number
  cost: number
  latency_ms: number
}

export interface InteractionDetail extends InteractionSummary {
  steps: InteractionStep[]
}
