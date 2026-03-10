import { useState } from 'react'
import { getOpLabel } from './opLabels'
import type { InteractionStep } from '@/types/traces'

interface StepBlockProps {
  step: InteractionStep
}

export function StepBlock({ step }: StepBlockProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const toggle = (key: string) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const label = getOpLabel(step.op)

  return (
    <div className="rounded-lg border border-border-subtle bg-white/5 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-text-light">
          Step {step.step_order} — {label}
        </span>
        <span className="text-xs text-text-muted">{step.latency_ms}ms</span>
      </div>
      <div className="text-xs text-text-muted">
        Model: {step.model} · {step.input_tokens} in · {step.output_tokens} out
        {step.cost > 0 && ` · $${step.cost.toFixed(6)}`}
      </div>

      {/* Collapsible message blocks */}
      {step.messages.map((msg, i) => (
        <CollapsibleBlock
          key={i}
          label={`${msg.role.charAt(0).toUpperCase() + msg.role.slice(1)} Prompt`}
          content={msg.content}
          expanded={expanded[`msg-${i}`] ?? false}
          onToggle={() => toggle(`msg-${i}`)}
        />
      ))}
      <CollapsibleBlock
        label="Response"
        content={step.raw_response}
        expanded={expanded.response ?? false}
        onToggle={() => toggle('response')}
      />
    </div>
  )
}

function CollapsibleBlock({
  label,
  content,
  expanded,
  onToggle,
}: {
  label: string
  content: string
  expanded: boolean
  onToggle: () => void
}) {
  const truncated = content.length > 200 && !expanded
  const display = truncated ? content.slice(0, 200) + '…' : content

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-1 text-xs font-medium text-text-muted hover:text-text-light transition-colors mb-1"
      >
        <span className="material-symbols-outlined !text-sm">
          {expanded ? 'expand_less' : 'expand_more'}
        </span>
        {label}
      </button>
      <pre className="text-xs text-text-light bg-black/30 rounded p-3 overflow-x-auto whitespace-pre-wrap font-mono max-h-64 overflow-y-auto">
        {display}
      </pre>
    </div>
  )
}
