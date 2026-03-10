import { create } from 'zustand'
import type { Message } from '@/types/api'
import { api } from '@/services/api'

const DEFAULT_USER_ID = 'dev_user'

// Watchdog timer handles (module-level to survive store updates)
let decodeWatchdog: ReturnType<typeof setTimeout> | null = null
let encodeWatchdog: ReturnType<typeof setTimeout> | null = null
let currentAbort: (() => void) | null = null

function clearWatchdogs() {
  if (decodeWatchdog) { clearTimeout(decodeWatchdog); decodeWatchdog = null }
  if (encodeWatchdog) { clearTimeout(encodeWatchdog); encodeWatchdog = null }
}

interface ChatStore {
  messages: Message[]
  isLoading: boolean
  streamingMessageId: string | null
  decodeStatus: 'idle' | 'running' | 'done'
  decodeStep: string | null
  encodeStatus: 'idle' | 'running' | 'done'
  encodeStep: string | null
  currentTurnId: string | null
  error: string | null
  lastFailedMessage: string | null
  userId: string

  sendMessage: (content: string) => void
  retryMessage: () => void
  clearMessages: () => void
  loadMessages: () => Promise<void>
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  isLoading: false,
  streamingMessageId: null,
  decodeStatus: 'idle',
  decodeStep: null,
  encodeStatus: 'idle',
  encodeStep: null,
  currentTurnId: null,
  error: null,
  lastFailedMessage: null,
  userId: DEFAULT_USER_ID,

  sendMessage: (content: string) => {
    const { userId } = get()

    // Abort any in-flight stream (follow-up while encode is running)
    if (currentAbort) {
      currentAbort()
      currentAbort = null
    }
    clearWatchdogs()

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    }
    set({
      messages: [...get().messages, userMessage],
      isLoading: true,
      error: null,
      lastFailedMessage: null,
      decodeStatus: 'idle',
      decodeStep: null,
      encodeStatus: 'idle',
      encodeStep: null,
      currentTurnId: null,
    })

    const streamingId = `streaming-${Date.now()}`
    let firstToken = true

    const abort = api.streamChat(userId, content, {
      onDecodeStart: () => {
        set({ decodeStatus: 'running', decodeStep: null })
        // 30s watchdog for decode phase
        decodeWatchdog = setTimeout(() => {
          set({ decodeStatus: 'idle', decodeStep: null })
        }, 30_000)
      },

      onDecodeStep: (step) => {
        // Reset watchdog on any progress
        if (decodeWatchdog) { clearTimeout(decodeWatchdog); decodeWatchdog = null }
        decodeWatchdog = setTimeout(() => {
          set({ decodeStatus: 'idle', decodeStep: null })
        }, 30_000)
        set({ decodeStep: step })
      },

      onDecodeDone: () => {
        if (decodeWatchdog) { clearTimeout(decodeWatchdog); decodeWatchdog = null }
        set({ decodeStatus: 'done', decodeStep: null })
      },

      onToken: (delta) => {
        if (firstToken) {
          firstToken = false
          const streamingMessage: Message = {
            id: streamingId,
            role: 'assistant',
            content: delta,
            timestamp: new Date().toISOString(),
          }
          set({
            messages: [...get().messages, streamingMessage],
            streamingMessageId: streamingId,
            decodeStatus: 'idle',
          })
        } else {
          set({
            messages: get().messages.map((m) =>
              m.id === streamingId ? { ...m, content: m.content + delta } : m
            ),
          })
        }
      },

      onDone: (finalMessage) => {
        set({
          messages: get().messages.map((m) => (m.id === streamingId ? finalMessage : m)),
          isLoading: false,
          streamingMessageId: null,
        })
      },

      onEncodeStart: () => {
        set({ encodeStatus: 'running', encodeStep: null })
        // 120s watchdog for encode phase
        encodeWatchdog = setTimeout(async () => {
          const { currentTurnId } = get()
          // Polling fallback: check DB for encode status
          if (currentTurnId) {
            try {
              const entries = await api.getTurnStatus(currentTurnId)
              const enc = entries.find((e) => e.phase === 'encode')
              if (enc?.status === 'done') {
                set({ encodeStatus: 'done', encodeStep: null })
                setTimeout(() => set({ encodeStatus: 'idle' }), 2000)
                return
              }
            } catch {
              // fall through to silent dismiss
            }
          }
          set({ encodeStatus: 'idle', encodeStep: null })
        }, 120_000)
      },

      onEncodeStep: (step) => {
        // Reset watchdog on any progress
        if (encodeWatchdog) { clearTimeout(encodeWatchdog); encodeWatchdog = null }
        encodeWatchdog = setTimeout(() => {
          set({ encodeStatus: 'idle', encodeStep: null })
        }, 120_000)
        set({ encodeStep: step })
      },

      onEncodeDone: (turnId) => {
        if (encodeWatchdog) { clearTimeout(encodeWatchdog); encodeWatchdog = null }
        set({ encodeStatus: 'done', encodeStep: null, currentTurnId: turnId })
        // Brief "done" state, then clear
        setTimeout(() => set({ encodeStatus: 'idle' }), 2000)
        currentAbort = null
      },

      onError: (err) => {
        console.error('Stream error:', err)
        clearWatchdogs()
        currentAbort = null
        set({
          messages: get().messages.filter((m) => m.id !== streamingId),
          isLoading: false,
          streamingMessageId: null,
          decodeStatus: 'idle',
          decodeStep: null,
          encodeStatus: 'idle',
          encodeStep: null,
          lastFailedMessage: content,
          error: 'Failed to get a response. Is the hippomem server running?',
        })
      },
    })

    currentAbort = abort
  },

  retryMessage: () => {
    const { lastFailedMessage, sendMessage } = get()
    if (!lastFailedMessage) return
    sendMessage(lastFailedMessage)
  },

  clearMessages: () => {
    clearWatchdogs()
    if (currentAbort) { currentAbort(); currentAbort = null }
    set({
      messages: [],
      error: null,
      lastFailedMessage: null,
      decodeStatus: 'idle',
      decodeStep: null,
      encodeStatus: 'idle',
      encodeStep: null,
      currentTurnId: null,
    })
  },

  loadMessages: async () => {
    const { userId } = get()
    try {
      const messages = await api.getMessages(userId)
      set({ messages })
    } catch {
      // non-fatal — start with empty chat if load fails
    }
  },
}))
