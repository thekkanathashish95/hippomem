import { MemoryExplorer } from '@/components/memory/MemoryExplorer'

export function MemoryLayout() {
  return (
    <main className="flex-1 flex flex-col bg-pure-black relative overflow-hidden">
      <MemoryExplorer />
    </main>
  )
}
