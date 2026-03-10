import { useEffect, useRef, useState } from 'react'
import { useChatStore } from '@/stores/chatStore'
import { Message } from './Message'

export function ChatMessages() {
  const {
    messages,
    isLoading,
    streamingMessageId,
    decodeStep,
    encodeStatus,
    encodeStep,
    error,
    retryMessage,
    loadMessages,
  } = useChatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)

  useEffect(() => {
    loadMessages()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading, encodeStatus])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container
      setShowScrollButton(scrollHeight - scrollTop - clientHeight > 100 && messages.length > 0)
    }
    container.addEventListener('scroll', handleScroll)
    return () => container.removeEventListener('scroll', handleScroll)
  }, [messages.length])

  const thinkingLabel = decodeStep ?? 'Thinking...'

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto p-5 md:p-8 space-y-8 scroll-smooth custom-scrollbar relative"
    >
      {messages.length === 0 && !isLoading && (
        <div className="h-full flex flex-col items-center justify-center text-center gap-2 opacity-50">
          <span className="material-symbols-outlined !text-4xl text-text-muted">chat</span>
          <p className="text-text-muted text-sm">Start a conversation to test hippomem.</p>
          <p className="text-text-muted text-xs">
            Memory context retrieved by recall() will appear under assistant replies.
          </p>
        </div>
      )}

      {messages.map((msg) => (
        <Message key={msg.id} message={msg} />
      ))}

      {/* Decode phase indicator — shown before first token arrives */}
      {isLoading && streamingMessageId === null && (
        <div className="max-w-3xl mx-auto">
          <div className="flex items-center gap-1.5 text-text-muted">
            <div className="w-1 h-1 bg-primary rounded-full animate-bounce [animation-delay:-0.3s]" />
            <div className="w-1 h-1 bg-primary rounded-full animate-bounce [animation-delay:-0.15s]" />
            <div className="w-1 h-1 bg-primary rounded-full animate-bounce" />
            <span className="ml-1 text-[11px] font-semibold uppercase tracking-wider">
              {thinkingLabel}
            </span>
          </div>
        </div>
      )}

      {/* Encode phase badge — shown after LLM response while encoding is in progress */}
      {(encodeStatus === 'running' || encodeStatus === 'done') && (
        <div className="max-w-3xl mx-auto space-y-1.5">
          <div className="flex items-center gap-2">
            {encodeStatus === 'running' ? (
              <>
                <svg
                  className="w-3 h-3 text-primary animate-spin shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
                <span className="text-[11px] font-semibold text-primary uppercase tracking-wider">
                  {encodeStep ?? 'Saving to memory...'}
                </span>
              </>
            ) : (
              <>
                <span className="material-symbols-outlined !text-xs text-primary">check_circle</span>
                <span className="text-[11px] font-semibold text-primary uppercase tracking-wider">
                  Memory saved
                </span>
              </>
            )}
          </div>
          {encodeStatus === 'running' && (
            <p className="text-[11px] text-text-muted leading-relaxed">
              Memory encoding in progress. For best results, wait before sending a follow-up.
            </p>
          )}
        </div>
      )}

      {error && (
        <div className="max-w-3xl mx-auto">
          <div className="flex items-center gap-3 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
            <p className="text-red-400 text-xs flex-1">{error}</p>
            <button
              type="button"
              onClick={retryMessage}
              className="flex items-center gap-1 text-red-400 hover:text-red-300 text-xs font-semibold shrink-0 transition-colors"
            >
              <span className="material-symbols-outlined !text-sm">refresh</span>
              Retry
            </button>
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />

      {showScrollButton && (
        <button
          type="button"
          onClick={() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })}
          className="absolute bottom-32 right-6 w-8 h-8 rounded-full bg-user-message shadow-2xl border border-border-subtle flex items-center justify-center text-text-muted hover:text-white transition-all hover:-translate-y-0.5"
        >
          <span className="material-symbols-outlined !text-lg">arrow_downward</span>
        </button>
      )}
    </div>
  )
}
