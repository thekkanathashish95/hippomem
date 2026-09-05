import { create } from 'zustand'
import { studioError } from '@/lib/errors'
import { api } from '@/services/api'
import type { InteractionSummary, InteractionDetail } from '@/types/traces'

interface TracesStore {
  interactions: InteractionSummary[]
  selectedInteraction: InteractionDetail | null
  isLoading: boolean
  isLoadingDetail: boolean
  error: string | null
  fetchTraces: (userId: string, limit?: number) => Promise<void>
  fetchInteractionDetail: (interactionId: string, userId: string) => Promise<void>
  clearSelection: () => void
}

export const useTracesStore = create<TracesStore>((set) => ({
  interactions: [],
  selectedInteraction: null,
  isLoading: false,
  isLoadingDetail: false,
  error: null,

  fetchTraces: async (userId: string, limit = 50) => {
    set({ isLoading: true, error: null })
    try {
      const data = await api.getTraces(userId, limit)
      set({ interactions: data, isLoading: false })
    } catch (err) {
      console.error('Failed to fetch traces:', err)
      set({
        isLoading: false,
        error: studioError('Failed to load traces', err),
      })
    }
  },

  fetchInteractionDetail: async (interactionId: string, userId: string) => {
    set({ isLoadingDetail: true })
    try {
      const detail = await api.getTraceDetail(interactionId, userId)
      set({ selectedInteraction: detail, isLoadingDetail: false })
    } catch (err) {
      console.error('Failed to fetch interaction detail:', err)
      set({ isLoadingDetail: false, selectedInteraction: null })
    }
  },

  clearSelection: () => set({ selectedInteraction: null }),
}))
