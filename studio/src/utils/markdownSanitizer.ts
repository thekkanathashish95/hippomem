const BLOCKED_IMAGE_DOMAINS = [
  /https?:\/\/api\./i,
  /https?:\/\/localhost/i,
  /https?:\/\/127\.0\.0\.1/i,
  /https?:\/\/192\.168\./i,
  /https?:\/\/10\./i,
  /https?:\/\/172\.(1[6-9]|2[0-9]|3[0-1])\./i,
]

export const shouldBlockImageUrl = (url: string | null | undefined): boolean => {
  if (!url) return false
  return BLOCKED_IMAGE_DOMAINS.some((pattern) => pattern.test(url))
}

export const sanitizeMarkdownImages = (content: string | null | undefined): string => {
  if (!content) return ''
  return content.replace(
    /!\[([^\]]*)\]\((https?:\/\/[^\)]+)\)/g,
    (match, _alt, url) => {
      if (shouldBlockImageUrl(url)) return ''
      return match
    }
  )
}
