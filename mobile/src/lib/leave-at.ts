/** "Leaving at" on Routes: turn the choice into the departure time to plan for. Pure, so it can be tested in Node. */
export type LeaveChoice = { kind: 'now' } | { kind: 'in'; min: number } | { kind: 'at'; hhmm: string }

/** ISO time to plan for, or null for now. A clock time already gone today means tomorrow. */
export function departAtFor(choice: LeaveChoice, now: Date): string | null {
  if (choice.kind === 'now') return null
  const d = new Date(now)
  d.setSeconds(0, 0)
  if (choice.kind === 'in') {
    d.setMinutes(d.getMinutes() + choice.min)
    return d.toISOString()
  }
  const [h, m] = choice.hhmm.split(':').map(Number)
  d.setHours(h, m)
  if (d.getTime() <= now.getTime()) d.setDate(d.getDate() + 1)
  return d.toISOString()
}

/** The next quarter-hour at least 15 minutes away, as "HH:MM": a sensible first value for the time picker. */
export function nextQuarter(now: Date): string {
  const d = new Date(now.getTime() + 15 * 60_000)
  d.setMinutes(Math.ceil(d.getMinutes() / 15) * 15, 0, 0)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
