import { useEffect } from 'react'
import { useChatStore } from '@/stores/chatStore'
import { useTracesStore } from '@/stores/tracesStore'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { RefreshButton } from '@/components/common/RefreshButton'
import { StepDetailPanel } from './StepDetailPanel'
import { formatDateTime } from '@/utils/formatDate'

export function TracesView() {
  const { userId } = useChatStore()
  const {
    interactions,
    selectedInteraction,
    isLoading,
    isLoadingDetail,
    error,
    fetchTraces,
    fetchInteractionDetail,
    clearSelection,
  } = useTracesStore()

  useEffect(() => {
    fetchTraces(userId)
  }, [userId, fetchTraces])

  const handleRowClick = (interactionId: string) => {
    fetchInteractionDetail(interactionId)
  }

  return (
    <div className="flex flex-col h-full">
      <header className="h-12 px-5 flex items-center justify-between flex-shrink-0 bg-pure-black/80 backdrop-blur-md border-b border-border-subtle">
        <h1 className="font-semibold text-xs text-white">Inspector</h1>
        <div className="flex items-center gap-2">
          <RefreshButton
            onClick={() => { clearSelection(); fetchTraces(userId) }}
            disabled={isLoading || isLoadingDetail}
            isLoading={isLoading}
          />
          {selectedInteraction && (
            <button
              type="button"
              onClick={clearSelection}
              className="text-xs text-text-muted hover:text-text-light flex items-center gap-1"
            >
              <span className="material-symbols-outlined !text-sm">arrow_back</span>
              back
            </button>
          )}
        </div>
      </header>

      <div className="flex-1 flex min-h-0">
        <div className="flex-1 min-w-0 overflow-auto">
          {isLoading ? (
            <div className="flex-1 flex items-center justify-center min-h-[200px]">
              <LoadingSpinner />
            </div>
          ) : error ? (
            <div className="flex-1 flex items-center justify-center min-h-[200px]">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-border-subtle text-text-muted text-xs uppercase tracking-wider">
                    <th className="py-3 px-4 font-medium">Timestamp</th>
                    <th className="py-3 px-4 font-medium">Operation</th>
                    <th className="py-3 px-4 font-medium">Steps</th>
                    <th className="py-3 px-4 font-medium">In tokens</th>
                    <th className="py-3 px-4 font-medium">Out tokens</th>
                    <th className="py-3 px-4 font-medium">Cost</th>
                    <th className="py-3 px-4 font-medium">Latency</th>
                  </tr>
                </thead>
                <tbody>
                  {interactions.map((row) => (
                    <tr
                      key={row.id}
                      onClick={() => handleRowClick(row.id)}
                      className="border-b border-border-subtle hover:bg-white/5 cursor-pointer transition-colors"
                    >
                      <td className="py-3 px-4 text-text-light">
                        {row.created_at ? formatDateTime(row.created_at) : '—'}
                      </td>
                      <td className="py-3 px-4 text-text-light">
                        {row.operation}
                      </td>
                      <td className="py-3 px-4 text-text-muted">
                        {row.call_count}
                      </td>
                      <td className="py-3 px-4 text-text-muted">
                        {row.total_input_tokens.toLocaleString()}
                      </td>
                      <td className="py-3 px-4 text-text-muted">
                        {row.total_output_tokens.toLocaleString()}
                      </td>
                      <td className="py-3 px-4 text-text-muted">
                        {row.total_cost > 0 ? `$${row.total_cost.toFixed(6)}` : '—'}
                      </td>
                      <td className="py-3 px-4 text-text-muted">
                        {row.total_latency_ms}ms
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {interactions.length === 0 && !isLoading && (
                <div className="py-12 text-center text-text-muted text-sm">
                  No traces yet. Send a message in Chat to generate LLM calls.
                </div>
              )}
            </div>
          )}
        </div>

        {selectedInteraction && (
          <>
            {isLoadingDetail ? (
              <div className="w-[480px] flex items-center justify-center bg-dark-sidebar border-l border-border-subtle">
                <LoadingSpinner />
              </div>
            ) : (
              <StepDetailPanel
                detail={selectedInteraction}
                onClose={clearSelection}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}
