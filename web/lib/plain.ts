import type { Confidence, Disruption, Leg, RouteOption } from './types'

// Plain-language wording for numbers and model output. Pure helpers, no UI.

/** "usually 32–38 min" from a p10/p90 pair. Collapses to a single value when the two round the same. */
export function usuallyRange(low: number | null | undefined, high: number | null | undefined) {
  if (low == null || high == null || !Number.isFinite(low) || !Number.isFinite(high)) return null
  const a = Math.round(low)
  const b = Math.round(high)
  return a === b ? `usually ${a} min` : `usually ${a}\u2013${b} min`
}

export const CONFIDENCE_PLAIN: Record<Confidence, { label: string; meaning: string }> = {
  high: { label: 'Reliable estimate', meaning: 'Live information agrees, so this time is unlikely to change much.' },
  medium: { label: 'Fairly reliable', meaning: 'Usually right. Allow a few minutes either way.' },
  low: { label: 'Rough estimate', meaning: 'Things could run quicker or slower than shown, so leave a bit of spare time.' },
}

/** Chance of arriving within 5 minutes of normal, as words. */
export function onTimeWords(chance: number | null | undefined) {
  if (chance == null || !Number.isFinite(chance)) return null
  if (chance >= 0.8) return { text: 'Likely on time', tone: 'success' as const }
  if (chance >= 0.5) return { text: 'Could run a little late', tone: 'watch' as const }
  return { text: 'Likely to be late', tone: 'attention' as const }
}

/** Chance that a brand-new disruption starts on a route during the trip. Quiet when it is small. */
export function newDelayRiskWords(risk: RouteOption['disruption_risk']) {
  if (risk == null || !Number.isFinite(risk) || risk < 0.05) return null
  if (risk < 0.15) return 'Small chance of new delays on the way'
  if (risk < 0.3) return 'Some chance of new delays on the way'
  return 'Higher chance of new delays on the way'
}

/** `chance_still_on` flows through the API on each disruption but isn't in the shared Disruption type. */
export function stillOnChance(d: Disruption): number | null {
  const v = (d as Disruption & { chance_still_on?: number | null }).chance_still_on
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

export function stillOnWords(chance: number | null) {
  if (chance == null) return null
  if (chance <= 0.25) return 'Likely cleared by the time you travel'
  if (chance >= 0.75) return 'Likely still affecting your trip'
  return 'May still be affecting your trip'
}

/** Quiet hint about where a leg's wait time came from. Falls back to the older `live` flag. */
export function waitBasisHint(leg: Pick<Leg, 'wait_basis' | 'live'>): { label: string; live: boolean } {
  switch (leg.wait_basis) {
    case 'live':
      return { label: 'Live', live: true }
    case 'timetable':
      return { label: 'Timetable', live: false }
    case 'frequency':
      return { label: 'Runs often', live: false }
    case 'typical':
      return { label: 'Estimate', live: false }
    default:
      return leg.live ? { label: 'Live', live: true } : { label: 'Timetable', live: false }
  }
}

export function crowdingWords(basis: string | null | undefined) {
  return basis ? `Crowding is an estimate. ${basis}` : 'Crowding is an estimate'
}
