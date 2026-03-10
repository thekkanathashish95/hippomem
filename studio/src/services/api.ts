import axios from 'axios'
import type { ChatResponse, Message, StreamChatCallbacks, TurnStatusEntry } from '@/types/api'
import type { GraphResponse, EventDetail, SelfTraitsResponse, EntitiesResponse } from '@/types/memory'
import type { DashboardStats } from '@/types/dashboard'
import type { InteractionSummary, InteractionDetail } from '@/types/traces'
import type { ConfigResponse, ConfigPatch, ConfigModelsResponse } from '@/types/settings'

// Empty string → relative URLs → Vite dev proxy handles routing to the backend.
// Set VITE_API_BASE_URL in .env when deploying (e.g. https://your-api.com).
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

export const api = {
  sendMessage: async (userId: string, message: string): Promise<ChatResponse> => {
    const response = await client.post('/chat', { user_id: userId, message })
    return response.data
  },

  streamChat: (userId: string, message: string, callbacks: StreamChatCallbacks): () => void => {
    const controller = new AbortController()
    const baseUrl = API_BASE_URL || ''
    let receivedDone = false

    // 300s global stream timeout (covers decode + LLM + encode)
    // Per-phase watchdogs in chatStore handle finer-grained timeouts
    const timeoutId = setTimeout(() => {
      if (!receivedDone) controller.abort()
    }, 300_000)

    fetch(`${baseUrl}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, message }),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          clearTimeout(timeoutId)
          callbacks.onError(new Error(`HTTP ${response.status}`))
          return
        }

        const reader = response.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        try {
          while (true) {
            const { done, value } = await reader.read()
            if (done) {
              clearTimeout(timeoutId)
              if (!receivedDone) callbacks.onError(new Error('Stream closed without completion'))
              break
            }

            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() ?? ''

            for (const line of lines) {
              if (!line.startsWith('data: ')) continue
              const data = JSON.parse(line.slice(6))
              if (data.type === 'token') {
                callbacks.onToken(data.delta)
              } else if (data.type === 'done') {
                callbacks.onDone(data.message)
              } else if (data.type === 'decode_start') {
                callbacks.onDecodeStart?.()
              } else if (data.type === 'decode_step') {
                callbacks.onDecodeStep?.(data.step)
              } else if (data.type === 'decode_done') {
                callbacks.onDecodeDone?.(data.used_events ?? 0)
              } else if (data.type === 'encode_start') {
                callbacks.onEncodeStart?.()
              } else if (data.type === 'encode_step') {
                callbacks.onEncodeStep?.(data.step)
              } else if (data.type === 'encode_done') {
                receivedDone = true
                clearTimeout(timeoutId)
                callbacks.onEncodeDone?.(data.turn_id)
              } else if (data.type === 'error') {
                clearTimeout(timeoutId)
                callbacks.onError(new Error(data.detail ?? 'Stream error'))
              }
            }
          }
        } catch (err) {
          clearTimeout(timeoutId)
          if ((err as Error).name !== 'AbortError') callbacks.onError(err as Error)
        }
      })
      .catch((err) => {
        clearTimeout(timeoutId)
        if (err.name !== 'AbortError') callbacks.onError(err)
      })

    return () => {
      clearTimeout(timeoutId)
      controller.abort()
    }
  },

  getMessages: async (userId: string): Promise<Message[]> => {
    const response = await client.get('/messages', { params: { user_id: userId } })
    return response.data
  },

  getGraph: async (userId: string): Promise<GraphResponse> => {
    const response = await client.get(`/memory/graph/${userId}`)
    return response.data
  },

  getEventDetail: async (userId: string, eventId: string): Promise<EventDetail> => {
    const response = await client.get(`/memory/events/${userId}/${eventId}`)
    return response.data
  },

  getSelfTraits: async (userId: string): Promise<SelfTraitsResponse> => {
    const response = await client.get(`/memory/self/${userId}`)
    return response.data
  },

  getEntities: async (userId: string): Promise<EntitiesResponse> => {
    const response = await client.get(`/memory/entities/${userId}`)
    return response.data
  },

  getStats: async (userId: string): Promise<DashboardStats> => {
    const response = await client.get('/stats', { params: { user_id: userId } })
    return response.data
  },

  getTraces: async (userId: string, limit = 50): Promise<InteractionSummary[]> => {
    const response = await client.get('/traces', {
      params: { user_id: userId, limit },
    })
    return response.data.interactions
  },

  getTraceDetail: async (interactionId: string): Promise<InteractionDetail> => {
    const response = await client.get(`/traces/${interactionId}`)
    return response.data
  },

  getTurnStatus: async (turnId: string): Promise<TurnStatusEntry[]> => {
    const response = await client.get(`/turn-status/${turnId}`)
    return response.data
  },

  getHealth: async (): Promise<{ status: string; setup_required: boolean }> => {
    const response = await client.get('/health')
    return response.data
  },

  getConfig: async (): Promise<ConfigResponse> => {
    const response = await client.get('/config')
    return response.data
  },

  patchConfig: async (patch: ConfigPatch): Promise<{ status: string; config: ConfigResponse }> => {
    const response = await client.patch('/config', patch)
    return response.data
  },

  getConfigModels: async (apiKey?: string, baseUrl?: string): Promise<ConfigModelsResponse> => {
    const params: Record<string, string> = {}
    if (apiKey) params.api_key = apiKey
    if (baseUrl) params.base_url = baseUrl
    const response = await client.get<ConfigModelsResponse>('/config/models', { params })
    return response.data
  },
}
