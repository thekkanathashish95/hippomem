/**
 * Parse an ISO datetime string as UTC, appending 'Z' if no timezone offset is
 * present. Server-side Python naive datetimes serialize without a suffix (e.g.
 * "2024-01-15T10:30:00"), which JS would interpret as local time — incorrect
 * when the underlying data is UTC.
 */
function toUTCDate(iso: string): Date {
  if (!iso) return new Date(NaN)
  // Already has timezone info (ends with Z or ±HH:MM)
  if (iso.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(iso)) {
    return new Date(iso)
  }
  // Naive datetime — treat as UTC
  return new Date(iso + 'Z')
}

/** Format a datetime as local date + time (e.g. "Jan 15, 2024, 10:30 AM") */
export function formatDateTime(iso: string): string {
  if (!iso) return '—'
  try {
    return toUTCDate(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

/** Format a datetime as local date only (e.g. "Jan 15, 2024") */
export function formatDate(iso: string): string {
  if (!iso) return '—'
  try {
    return toUTCDate(iso).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return '—'
  }
}
