import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useChatStore } from '@/stores/chatStore'
import { useDashboardStore } from '@/stores/dashboardStore'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { RefreshButton } from '@/components/common/RefreshButton'

export function DashboardView() {
  const { userId } = useChatStore()
  const { stats, isLoading, error, fetchStats } = useDashboardStore()

  useEffect(() => {
    fetchStats(userId)
  }, [userId, fetchStats])

  return (
    <main className="flex-1 flex flex-col bg-pure-black relative overflow-auto">
      <header className="h-12 px-5 flex items-center justify-between flex-shrink-0 bg-pure-black/80 backdrop-blur-md border-b border-border-subtle">
        <h1 className="font-semibold text-xs text-white">Dashboard</h1>
        <RefreshButton
          onClick={() => fetchStats(userId)}
          disabled={isLoading}
          isLoading={isLoading}
        />
      </header>

      <div className="flex-1 p-6 overflow-auto">
        {isLoading ? (
          <div className="flex-1 flex items-center justify-center min-h-[200px]">
            <LoadingSpinner />
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center min-h-[200px]">
            <p className="text-red-400 text-sm">{error}</p>
          </div>
        ) : stats ? (
          <div className="max-w-2xl space-y-8">
            {/* Memory stat cards */}
            <section>
              <h2 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-3">
                Memory
              </h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <StatCard
                  label="Memories"
                  value={stats.memory.total_engrams}
                  icon="psychology"
                />
                <StatCard
                  label="Active"
                  value={stats.memory.active}
                  icon="bolt"
                />
                <StatCard
                  label="Entities"
                  value={stats.memory.entities}
                  icon="person"
                />
              </div>
            </section>

            {/* Usage summary */}
            <section>
              <h2 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-3">
                Usage (all time)
              </h2>
              <div className="rounded-lg border border-border-subtle overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border-subtle bg-white/[0.03]">
                      <th className="text-left px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Metric</th>
                      <th className="text-right px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-subtle">
                    <tr className="bg-white/[0.02]">
                      <td className="px-4 py-2.5 text-text-muted">Total memory interactions</td>
                      <td className="px-4 py-2.5 text-right font-medium text-text-light tabular-nums">
                        {stats.usage.total_interactions.toLocaleString()}
                      </td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2.5 text-text-muted">Total tokens used</td>
                      <td className="px-4 py-2.5 text-right font-medium text-text-light tabular-nums">
                        {stats.usage.total_tokens.toLocaleString()}
                      </td>
                    </tr>
                    <tr className="bg-white/[0.02]">
                      <td className="px-4 py-2.5 text-text-muted">Input tokens</td>
                      <td className="px-4 py-2.5 text-right font-medium text-text-light tabular-nums">
                        {stats.usage.total_input_tokens.toLocaleString()}
                      </td>
                    </tr>
                    <tr>
                      <td className="px-4 py-2.5 text-text-muted">Output tokens</td>
                      <td className="px-4 py-2.5 text-right font-medium text-text-light tabular-nums">
                        {stats.usage.total_output_tokens.toLocaleString()}
                      </td>
                    </tr>
                    <tr className="bg-white/[0.02]">
                      <td className="px-4 py-2.5 text-text-muted">Estimated cost</td>
                      <td className="px-4 py-2.5 text-right font-medium text-text-light tabular-nums">
                        ${stats.usage.total_cost.toFixed(4)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="mt-2.5 text-[11px] text-text-muted leading-relaxed">
                A dedicated Usage page is coming in a future release — with per-operation breakdowns, token trends over time, and cost tracking by memory type.
              </p>
            </section>

            {/* Action buttons */}
            <section className="flex flex-wrap gap-3">
              <Link
                to="/chat"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary/20 text-primary hover:bg-primary/30 text-sm font-medium transition-colors"
              >
                <span className="material-symbols-outlined !text-lg">chat</span>
                Open Chat
              </Link>
              <Link
                to="/memory"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-white/5 text-text-light hover:bg-white/10 text-sm font-medium transition-colors border border-border-subtle"
              >
                <span className="material-symbols-outlined !text-lg">psychology</span>
                Memory Explorer
              </Link>
              <Link
                to="/traces"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-white/5 text-text-light hover:bg-white/10 text-sm font-medium transition-colors border border-border-subtle"
              >
                <span className="material-symbols-outlined !text-lg">bug_report</span>
                Inspector
              </Link>
            </section>
          </div>
        ) : (
          <div className="text-text-muted text-sm">
            No stats yet. Send a message in Chat to populate memory and usage.
          </div>
        )}
      </div>
    </main>
  )
}

function StatCard({
  label,
  value,
  icon,
}: {
  label: string
  value: number
  icon: string
}) {
  return (
    <div className="rounded-lg border border-border-subtle bg-white/5 p-4">
      <div className="text-2xl font-semibold text-white">{value}</div>
      <div className="text-xs text-text-muted mt-0.5 flex items-center gap-1.5">
        <span className="material-symbols-outlined !text-sm">{icon}</span>
        {label}
      </div>
    </div>
  )
}
