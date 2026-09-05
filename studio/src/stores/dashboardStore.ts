import { create } from 'zustand'
import { studioError } from '@/lib/errors'
import { api } from '@/services/api'
import type { DashboardStats } from '@/types/dashboard'

interface DashboardStore {
  stats: DashboardStats | null
  isLoading: boolean
  error: string | null
  fetchStats: (userId: string) => Promise<void>
}

export const useDashboardStore = create<DashboardStore>((set) => ({
  stats: null,
  isLoading: false,
  error: null,

  fetchStats: async (userId: string) => {
    set({ isLoading: true, error: null })
    try {
      const data = await api.getStats(userId)
      set({ stats: data, isLoading: false })
    } catch (err) {
      console.error('Failed to fetch dashboard stats:', err)
      set({
        isLoading: false,
        error: studioError('Failed to load dashboard', err),
      })
    }
  },
}))
