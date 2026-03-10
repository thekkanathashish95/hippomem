export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  memory_context?: string | null
  timestamp: string
}

export interface ChatRequest {
  user_id: string
  message: string
}

export interface ChatResponse {
  message: Message
}

export interface StreamChatCallbacks {
  onToken: (delta: string) => void
  onDone: (message: Message) => void
  onError: (err: Error) => void
  onDecodeStart?: () => void
  onDecodeStep?: (step: string) => void
  onDecodeDone?: (usedEvents: number) => void
  onEncodeStart?: () => void
  onEncodeStep?: (step: string) => void
  onEncodeDone?: (turnId: string) => void
}

export interface TurnStatusEntry {
  phase: 'decode' | 'encode'
  status: 'running' | 'done' | 'error'
  current_step: string | null
  started_at: string | null
  completed_at: string | null
}
