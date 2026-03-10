import { ChatMessages } from '@/components/chat/ChatMessages'
import { ChatComposer } from '@/components/chat/ChatComposer'

export function ChatLayout() {
  return (
    <main className="flex-1 flex flex-col bg-pure-black relative">
      <ChatMessages />
      <ChatComposer />
    </main>
  )
}
