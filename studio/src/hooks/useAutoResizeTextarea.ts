import { useEffect, useRef } from 'react'

interface UseAutoResizeTextareaOptions {
  maxHeight?: number
  minHeight?: number
}

export const useAutoResizeTextarea = (options: UseAutoResizeTextareaOptions = {}) => {
  const { maxHeight = 160, minHeight = 48 } = options
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const adjustHeight = () => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    const next = Math.min(textarea.scrollHeight, maxHeight)
    textarea.style.height = `${Math.max(next, minHeight)}px`
  }

  const resetHeight = () => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
  }

  useEffect(() => {
    adjustHeight()
  }, [])

  return { textareaRef, adjustHeight, resetHeight }
}
