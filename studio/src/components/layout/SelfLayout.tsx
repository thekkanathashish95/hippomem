import { SelfMemoryView } from '@/components/memory/SelfMemoryView'

export function SelfLayout() {
  return (
    <main className="flex-1 flex flex-col bg-pure-black relative overflow-hidden">
      <SelfMemoryView />
    </main>
  )
}
