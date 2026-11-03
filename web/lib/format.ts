import type { Confidence, LineCategory, Preference } from './types'

const LONDON = 'Europe/London'

const timeFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: LONDON,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

/** "08:43" in Europe/London. */
export function fmtTime(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return timeFmt.format(d)
}

/** "44 min" / "1 h 5 min". Never decimals. */
export function fmtMin(min: number | null | undefined) {
  if (min == null || !Number.isFinite(min)) return '—'
  const m = Math.max(0, Math.round(min))
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r ? `${h} h ${r} min` : `${h} h`
}

/** Whole minutes only. */
export const roundMin = (min: number) => Math.round(min)

/** "+11 min" / "−6 min" / "same". */
export function fmtDelta(min: number | null | undefined) {
  if (min == null || !Number.isFinite(min)) return null
  const m = Math.round(min)
  if (m === 0) return 'same'
  return m > 0 ? `+${m} min` : `\u2212${Math.abs(m)} min`
}

export function fmtPct(v: number | null | undefined) {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${Math.round(v * 100)}%`
}

export function fmtAgoSeconds(s: number | null | undefined) {
  if (s == null || !Number.isFinite(s)) return 'unknown'
  const sec = Math.max(0, Math.round(s))
  if (sec < 60) return `${sec} s ago`
  const m = Math.round(sec / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}

export function fmtAgo(iso: string, now = Date.now()) {
  return fmtAgoSeconds((now - new Date(iso).getTime()) / 1000)
}

export function fmtWait(min: number) {
  const m = Math.round(min)
  return m <= 0 ? 'due now' : `next in ${m} min`
}

export function londonHour(now = new Date()) {
  return Number(
    new Intl.DateTimeFormat('en-GB', { timeZone: LONDON, hour: '2-digit', hour12: false }).format(now),
  )
}

export function greeting(name: string | null | undefined, now = new Date()) {
  const h = londonHour(now)
  const part = h < 12 ? 'Morning' : h < 18 ? 'Afternoon' : 'Evening'
  return name ? `${part}, ${name}` : `Good ${part.toLowerCase()}`
}

export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const

export function fmtDays(days: number[]) {
  const s = [...days].sort((a, b) => a - b)
  const key = s.join(',')
  if (key === '0,1,2,3,4') return 'Weekdays'
  if (key === '0,1,2,3,4,5,6') return 'Every day'
  if (key === '5,6') return 'Weekends'
  return s.map((d) => DAY_LABELS[d]).join(', ')
}

export const PREFERENCE_LABELS: Record<Preference, string> = {
  balanced: 'Balanced',
  fastest: 'Fastest',
  reliable: 'Most reliable',
  least_walking: 'Least walking',
  fewest_changes: 'Fewest changes',
}

export const PREFERENCES = Object.keys(PREFERENCE_LABELS) as Preference[]

export const CONFIDENCE_LABELS: Record<Confidence, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
}

export const CATEGORY_LABELS: Record<LineCategory, string> = {
  good: 'Good service',
  minor: 'Minor delays',
  severe: 'Severe delays',
  part_suspended: 'Part suspended',
  suspended: 'Suspended',
}
