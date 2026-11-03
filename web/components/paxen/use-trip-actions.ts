'use client'

import { useState } from 'react'
import { mutate } from 'swr'
import { api } from '@/lib/api'
import { activeTripStore } from '@/lib/hooks'
import type { RouteOption } from '@/lib/types'

export function useStartTrip() {
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const start = async (commuteId: string, option: RouteOption) => {
    setPending(option.id)
    setError(null)
    try {
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

export async function arriveTrip(id: string) {
  const trip = await api.arrive(id)
  activeTripStore.set(null)
  mutate((key) => Array.isArray(key) && (key[0] === 'insights' || key[0] === 'dashboard'))
  return trip
}
