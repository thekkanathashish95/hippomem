import { StepBlock } from './StepBlock'
import type { InteractionDetail } from '@/types/traces'
import { formatDateTime } from '@/utils/formatDate'

interface StepDetailPanelProps {
  detail: InteractionDetail
  onClose: () => void
}

export function StepDetailPanel({ detail, onClose }: StepDetailPanelProps) {
  const created = detail.created_at ? formatDateTime(detail.created_at) : ''

  return (
    <div className="panel-slide-in flex flex-col h-full bg-dark-sidebar border-l border-border-subtle w-[480px] min-w-[400px] overflow-hidden">
      <header className="flex-shrink-0 px-4 py-3 border-b border-border-subtle flex items-center justify-between">
        <h3 className="font-semibold text-sm text-white">
          {detail.operation} · {created} · {detail.call_count} steps
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="p-1 rounded hover:bg-white/10 text-text-muted hover:text-text-light transition-colors"
          aria-label="Close"
        >
          <span className="material-symbols-outlined !text-lg">close</span>
        </button>
      </header>
      <div className="text-xs text-text-muted px-4 py-2 border-b border-border-subtle">
        {detail.total_input_tokens} in / {detail.total_output_tokens} out /{' '}
        {detail.total_latency_ms}ms total
        {detail.total_cost > 0 && ` / $${detail.total_cost.toFixed(6)}`}
      </div>
      {detail.turn_id && (
        <div className="text-xs text-text-muted px-4 py-2 border-b border-border-subtle flex items-center gap-2">
          <span className="text-text-dim">turn</span>
          <code
            className="font-mono text-text-light cursor-pointer hover:text-white"
            title="Click to copy turn_id"
            onClick={() => navigator.clipboard.writeText(detail.turn_id!)}
          >
            {detail.turn_id}
          </code>
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
        {detail.steps.map((step) => (
          <StepBlock key={step.step_order} step={step} />
        ))}
      </div>
    </div>
  )
}
