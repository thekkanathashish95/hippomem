import { useEffect, useState } from 'react'
import { useChatStore } from '@/stores/chatStore'
import { useMemoryStore, type ViewMode } from '@/stores/memoryStore'
import { ViewToggle } from './ViewToggle'
import { ListView } from './ListView'
import { GridView } from './GridView'
import { GraphView } from './GraphView'
import { EventDetailPanel } from './EventDetailPanel'
import { EmptyState } from './EmptyState'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { RefreshButton } from '@/components/common/RefreshButton'

export function MemoryExplorer() {
  const { userId } = useChatStore()
  const {
    nodes,
    edges,
    selectedEvent,
    isLoading,
    isLoadingDetail,
    error,
    fetchGraph,
    fetchEventDetail,
    clearSelection,
  } = useMemoryStore()

  const [activeView, setActiveView] = useState<ViewMode>('list')

  useEffect(() => {
    fetchGraph(userId)
  }, [userId, fetchGraph])

  const handleSelectEvent = (eventId: string) => {
    fetchEventDetail(userId, eventId)
  }

  const hasData = nodes.length > 0

  return (
    <div className="flex flex-col h-full">
      <header className="h-12 px-5 flex items-center justify-between flex-shrink-0 bg-pure-black/80 backdrop-blur-md border-b border-border-subtle">
        <h1 className="font-semibold text-xs text-white">Memory Explorer</h1>
        <div className="flex items-center gap-2">
          <RefreshButton
            onClick={() => { clearSelection(); fetchGraph(userId) }}
            disabled={isLoading || isLoadingDetail}
            isLoading={isLoading}
          />
          {hasData && <ViewToggle activeView={activeView} onViewChange={setActiveView} />}
        </div>
      </header>

      <div className="flex-1 flex min-h-0 relative">
        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <LoadingSpinner />
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-red-400 text-sm">{error}</p>
          </div>
        ) : !hasData ? (
          <EmptyState />
        ) : (
          <>
            <div className="flex-1 min-w-0 overflow-auto">
              {activeView === 'list' && (
                <ListView nodes={nodes} onSelectEvent={handleSelectEvent} />
              )}
              {activeView === 'grid' && (
                <GridView nodes={nodes} onSelectEvent={handleSelectEvent} />
              )}
              {activeView === 'graph' && (
                <GraphView nodes={nodes} edges={edges} onSelectEvent={handleSelectEvent} />
              )}
            </div>
            <EventDetailPanel
              event={selectedEvent}
              isLoading={isLoadingDetail}
              onClose={clearSelection}
            />
          </>
        )}
      </div>
    </div>
  )
}
