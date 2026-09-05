export function studioError(action: string, err?: unknown): string {
  const status = (err as { response?: { status?: number } } | undefined)?.response?.status
  if (status === 401 || status === 403) {
    return `${action} was rejected. If the daemon requires a token, add it in Settings.`
  }
  return `${action}. Confirm the hippomem server is running and an LLM API key is set in Settings.`
}
