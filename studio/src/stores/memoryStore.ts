import { create } from 'zustand'
import { api } from '@/services/api'
import type { MemoryNode, MemoryEdge, EventDetail } from '@/types/memory'

export type ViewMode = 'list' | 'grid' | 'graph'

interface MemoryStore {
  nodes: MemoryNode[]
  edges: MemoryEdge[]
  selectedEvent: EventDetail | null
  isLoading: boolean
  isLoadingDetail: boolean
  error: string | null

  fetchGraph: (userId: string) => Promise<void>
  fetchEventDetail: (userId: string, eventId: string) => Promise<void>
  clearSelection: () => void
}

export const useMemoryStore = create<MemoryStore>((set) => ({
  nodes: [],
  edges: [],
  selectedEvent: null,
  isLoading: false,
  isLoadingDetail: false,
  error: null,

  fetchGraph: async (userId: string) => {
    set({ isLoading: true, error: null })
    try {
      const data = await api.getGraph(userId)
      set({ nodes: data.nodes, edges: data.edges, isLoading: false })
    } catch (err) {
      console.error('Failed to fetch memory graph:', err)
      set({
        isLoading: false,
        error: 'Failed to load memory. Is the hippomem server running?',
      })
    }
  },

  fetchEventDetail: async (userId: string, eventId: string) => {
    set({ isLoadingDetail: true })
    try {
      const detail = await api.getEventDetail(userId, eventId)
      set({ selectedEvent: detail, isLoadingDetail: false })
    } catch (err) {
      console.error('Failed to fetch event detail:', err)
      set({ isLoadingDetail: false, selectedEvent: null })
    }
  },

  clearSelection: () => set({ selectedEvent: null }),
}))
