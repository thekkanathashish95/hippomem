import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import type { Message as MessageType } from '@/types/api'
import { sanitizeMarkdownImages, shouldBlockImageUrl } from '@/utils/markdownSanitizer'
import {
  Tooltip,
  TooltipContent,
  TooltipPortal,
  TooltipTrigger,
} from '@/components/ui/tooltip'

function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp)
    if (Number.isNaN(date.getTime())) return timestamp
    return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return timestamp
  }
}

interface MessageProps {
  message: MessageType
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)
  const [memoryOpen, setMemoryOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!memoryOpen) return
    const handle = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMemoryOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [memoryOpen])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  if (isUser) {
    return (
      <div className="max-w-3xl mx-auto flex justify-end group w-full">
        <div className="flex flex-col items-end gap-1 w-full min-w-0">
          <div className="max-w-[85%] w-fit bg-user-message p-3 px-4 rounded-xl rounded-tr-none border border-border-subtle">
            <p className="text-body-compact text-text-light whitespace-pre-wrap break-words">
              {message.content}
            </p>
          </div>
          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={handleCopy}
                  className="text-text-muted hover:text-white p-1 rounded hover:bg-white/10 transition-colors"
                  aria-label={copied ? 'Copied' : 'Copy'}
                >
                  <span className="material-symbols-outlined !text-sm">
                    {copied ? 'check' : 'content_copy'}
                  </span>
                </button>
              </TooltipTrigger>
              <TooltipPortal>
                <TooltipContent side="top">{copied ? 'Copied' : 'Copy'}</TooltipContent>
              </TooltipPortal>
            </Tooltip>
            <span className="text-[11px] text-text-muted opacity-60">{formatTime(message.timestamp)}</span>
          </div>
        </div>
      </div>
    )
  }

  const sanitizedContent = sanitizeMarkdownImages(message.content)

  return (
    <div className="max-w-3xl mx-auto group">
      <div className="flex-1 space-y-3">
        <div className="prose prose-invert max-w-none text-body-compact text-text-light">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>,
              code: (({ className, children, ...props }: { className?: string; children?: React.ReactNode; [k: string]: unknown }) => {
                // react-markdown v10 does not pass `inline`; detect block by language class or multi-line content
                const langMatch = className ? /language-(\w+)/.exec(className) : null
                const isBlock = langMatch || (children != null && String(children).includes('\n'))
                if (isBlock) {
                  const language = langMatch ? langMatch[1] : 'text'
                  return (
                    <div className="rounded-lg overflow-hidden my-3 border border-border-subtle">
                      <div className="flex justify-between items-center px-3 py-1.5 bg-[#1a1a1a] text-text-muted">
                        <span className="text-[10px] font-bold uppercase tracking-wider">{language}</span>
                        <button
                          onClick={() => navigator.clipboard.writeText(String(children).replace(/\n$/, ''))}
                          className="cursor-pointer hover:text-white"
                        >
                          <span className="material-symbols-outlined !text-sm">content_copy</span>
                        </button>
                      </div>
                      <SyntaxHighlighter
                        style={oneDark}
                        language={language}
                        PreTag="div"
                        customStyle={{ margin: 0, borderRadius: 0, fontSize: '11px' }}
                      >
                        {String(children).replace(/\n$/, '')}
                      </SyntaxHighlighter>
                    </div>
                  )
                }
                return (
                  <code
                    className="bg-user-message px-1 py-0.5 rounded text-primary text-[12px] font-mono"
                    {...props}
                  >
                    {children}
                  </code>
                )
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              }) as any,
              pre: ({ children }) => <div className="my-3">{children}</div>,
              ul: ({ children }) => <ul className="list-disc list-inside my-2 space-y-1">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal list-inside my-2 space-y-1">{children}</ol>,
              li: ({ children }) => <li className="leading-relaxed">{children}</li>,
              a: ({ children, href }) => (
                <a href={href} className="text-primary hover:underline" target="_blank" rel="noopener noreferrer">
                  {children}
                </a>
              ),
              img: ({ src, alt, ...props }: any) => {
                if (shouldBlockImageUrl(src)) return null
                return (
                  <img
                    src={src}
                    alt={alt || ''}
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                    className="max-w-full rounded-lg my-2"
                    {...props}
                  />
                )
              },
              h1: ({ children }) => <h1 className="text-xl font-bold mt-4 mb-2">{children}</h1>,
              h2: ({ children }) => <h2 className="text-lg font-bold mt-3 mb-2">{children}</h2>,
              h3: ({ children }) => <h3 className="text-base font-bold mt-2 mb-1">{children}</h3>,
              blockquote: ({ children }) => (
                <blockquote className="border-l-4 border-border-subtle pl-4 my-2 text-text-muted">
                  {children}
                </blockquote>
              ),
            }}
          >
            {sanitizedContent}
          </ReactMarkdown>
        </div>

        {/* Memory context badge — visible when hippomem retrieved something */}
        {message.memory_context && (
          <div ref={menuRef} className="mt-2">
            <button
              type="button"
              onClick={() => setMemoryOpen((o) => !o)}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-primary text-[11px] font-semibold hover:bg-primary/20 transition-colors"
            >
              <span className="material-symbols-outlined !text-xs">memory</span>
              memory used
              <span className="material-symbols-outlined !text-xs">
                {memoryOpen ? 'expand_less' : 'expand_more'}
              </span>
            </button>
            {memoryOpen && (
              <div className="mt-2 p-3 rounded-lg bg-primary/5 border border-primary/15 text-[12px] text-text-muted font-mono whitespace-pre-wrap leading-relaxed">
                {message.memory_context}
              </div>
            )}
          </div>
        )}

        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={handleCopy}
                className="text-text-muted hover:text-white p-1 rounded hover:bg-white/10 transition-colors"
                aria-label={copied ? 'Copied' : 'Copy'}
              >
                <span className="material-symbols-outlined !text-sm">
                  {copied ? 'check' : 'content_copy'}
                </span>
              </button>
            </TooltipTrigger>
            <TooltipPortal>
              <TooltipContent side="top">{copied ? 'Copied' : 'Copy'}</TooltipContent>
            </TooltipPortal>
          </Tooltip>
          <span className="text-[11px] text-text-muted opacity-60">{formatTime(message.timestamp)}</span>
        </div>
      </div>
    </div>
  )
}
