export function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center gap-3 px-6">
      <span className="material-symbols-outlined !text-5xl text-text-muted opacity-60">
        psychology
      </span>
      <p className="text-text-muted text-sm max-w-[280px]">
        No memories yet. Start a conversation in Chat to build your memory graph.
      </p>
    </div>
  )
}
