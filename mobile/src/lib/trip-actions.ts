import { useState } from 'react'
import { mutate } from 'swr'
import type { RouteOption } from '@/shared/types'
import { api } from './api'
import { success } from './haptics'
import { activeTripStore } from './hooks'

async function begin(commuteId: string, option: RouteOption) {
  const trip = await api.startTrip({
    commute_id: commuteId,
    signature: option.id,
    summary: option.summary,
    forecast_p10: option.duration.p10,
    forecast_p50: option.duration.p50,
    forecast_p90: option.duration.p90,
  })
  activeTripStore.set({
    id: trip.id,
    commute_id: commuteId,
    signature: option.id,
    summary: option.summary,
    started_at: trip.started_at,
    forecast_p50: option.duration.p50,
  })
  success()
}

export function useStartTrip() {
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const start = async (commuteId: string, option: RouteOption) => {
    setPending(option.id)
    setError(null)
    try {
      await begin(commuteId, option)
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start this trip.')
      return false
    } finally {
      setPending(null)
    }
  }

  return { start, pending, error }
}

/**
 * "Start trip" on a notification: start the route Paxen recommends for that commute right now (the alert may be a
 * few minutes old, so it is looked up afresh). False when there's nothing to start.
 */
export async function startRecommended(commuteId: string): Promise<boolean> {
  const dashboard = await api.dashboard()
  const ev = dashboard.commutes.find((c) => c.commute.id === commuteId)
  const option = ev?.recommended
  if (!option || !option.feasible) return false
  await begin(commuteId, option)
  return true
}

/** Refresh what a finished trip changes. */
export const refreshAfterTrip = () =>
  mutate((key) => Array.isArray(key) && ['dashboard', 'insights', 'trips'].includes(key[0] as string))
