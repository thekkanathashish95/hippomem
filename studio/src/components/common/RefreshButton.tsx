import { cn } from '@/lib/utils'

interface RefreshButtonProps {
  onClick: () => void
  disabled?: boolean
  isLoading?: boolean
  title?: string
}

export function RefreshButton({
  onClick,
  disabled = false,
  isLoading = false,
  title = 'Refresh',
}: RefreshButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="p-1.5 rounded-md text-text-muted hover:text-text-light hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
    >
      <span
        className={cn(
          'material-symbols-outlined !text-base',
          isLoading && 'animate-spin'
        )}
      >
        refresh
      </span>
    </button>
  )
}
