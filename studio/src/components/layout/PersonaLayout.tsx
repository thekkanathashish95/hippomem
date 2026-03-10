import { PersonaView } from '@/components/memory/PersonaView'

export function PersonaLayout() {
  return (
    <main className="flex-1 flex flex-col bg-pure-black relative overflow-hidden">
      <PersonaView />
    </main>
  )
}
