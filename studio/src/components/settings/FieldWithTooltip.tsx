import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

interface FieldWithTooltipProps {
  label: string
  tooltip: string
  children: React.ReactNode
}

export function FieldWithTooltip({ label, tooltip, children }: FieldWithTooltipProps) {
  return (
    <div className="space-y-1.5">
      <label className="flex items-center gap-1.5 text-[13px] font-medium text-text-light">
        {label}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="text-text-muted hover:text-text-light transition-colors focus:outline-none"
              aria-label={`Info: ${label}`}
            >
              <span className="material-symbols-outlined !text-[14px]">info</span>
            </button>
          </TooltipTrigger>
          <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
      </label>
      {children}
    </div>
  )
}
