import { useState, useEffect, type KeyboardEvent } from 'react'
import { useChatStore } from '@/stores/chatStore'
import { useAutoResizeTextarea } from '@/hooks/useAutoResizeTextarea'

export function ChatComposer() {
  const [inputValue, setInputValue] = useState('')
  const { sendMessage, isLoading } = useChatStore()
  const { textareaRef, adjustHeight, resetHeight } = useAutoResizeTextarea({
    maxHeight: 144,
    minHeight: 36,
  })

  useEffect(() => {
    adjustHeight()
  }, [inputValue, adjustHeight])

  const handleSend = async () => {
    if (!inputValue.trim() || isLoading) return
    const content = inputValue.trim()
    setInputValue('')
    resetHeight()
    await sendMessage(content)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="p-5 pt-0 bg-pure-black">
      <div className="max-w-3xl mx-auto relative group">
        <div className="relative bg-user-message rounded-xl flex items-center p-1.5 transition-all outline-none ring-0 shadow-none overflow-hidden">
          <button type="button" className="p-1.5 text-text-muted hover:text-white flex-shrink-0">
            <span className="material-symbols-outlined !text-xl">attach_file</span>
          </button>
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={(e) => {
              setInputValue(e.target.value)
              adjustHeight()
            }}
            onKeyDown={handleKeyDown}
            className="flex-1 min-h-[2.25rem] bg-transparent border-0 border-none outline-none focus:ring-0 focus:outline-none focus-visible:outline-none text-body-compact leading-5 py-2 px-1 resize-none max-h-36 scrollbar-hide text-white placeholder-text-muted [&::-webkit-search-cancel-button]:hidden appearance-none"
            placeholder="Ask something..."
            rows={1}
          />
          <div className="flex items-center gap-1 p-0.5">
            <button
              type="button"
              onClick={handleSend}
              disabled={!inputValue.trim() || isLoading}
              className={`w-8 h-8 rounded-lg flex items-center justify-center transition-all active:scale-95 shadow-lg ${
                inputValue.trim() && !isLoading
                  ? 'bg-white hover:bg-gray-200 text-black'
                  : 'bg-white/20 text-white/40 cursor-not-allowed'
              }`}
            >
              {isLoading ? (
                <div className="w-4 h-4 border-2 border-black border-t-transparent rounded-full animate-spin" />
              ) : (
                <span className="material-symbols-outlined !text-lg">send</span>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
