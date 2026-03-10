import { TracesView } from '@/components/traces/TracesView'

export function TracesLayout() {
  return (
    <main className="flex-1 flex flex-col bg-pure-black relative overflow-hidden">
      <TracesView />
    </main>
  )
}
