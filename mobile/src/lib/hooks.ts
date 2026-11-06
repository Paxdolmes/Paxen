import { useMemo, useSyncExternalStore } from 'react'
import useSWR, { mutate as globalMutate } from 'swr'
import type { Preference } from '@/shared/types'
import { api, tokenStore } from './api'
import { persisted } from './storage'

export function useToken() {
  return useSyncExternalStore(tokenStore.subscribe, tokenStore.get, tokenStore.get)
}

const swrOpts = { revalidateOnFocus: true, shouldRetryOnError: false } as const

export function useDashboard(enabled = true) {
  return useSWR(enabled ? ['dashboard'] : null, () => api.dashboard(), {
    ...swrOpts,
    refreshInterval: 60_000,
    keepPreviousData: true,
  })
}

export function useCompare(commuteId: string | null | undefined, preference: Preference | undefined) {
  return useSWR(commuteId ? ['compare', commuteId, preference ?? ''] : null, () => api.compare(commuteId!, preference), {
    ...swrOpts,
    refreshInterval: 60_000,
    keepPreviousData: true,
  })
}

export function useNetwork() {
  return useSWR(['network'], () => api.network(), { ...swrOpts, refreshInterval: 60_000 })
}

export function useAlerts() {
  return useSWR(['alerts'], () => api.alerts(), swrOpts)
}

export function useInsights() {
  return useSWR(['insights'], () => api.insights(), swrOpts)
}

export function useScenarios(enabled: boolean) {
  return useSWR(enabled ? ['scenarios'] : null, () => api.devScenarios(), swrOpts)
}

export function usePlaceSearch(q: string) {
  const term = q.trim()
  return useSWR(term.length >= 2 ? ['places-search', term] : null, () => api.searchPlaces(term), {
    ...swrOpts,
    revalidateOnFocus: false,
    keepPreviousData: true,
  })
}

export function useNearbyStops(lat: number | null, lon: number | null) {
  return useSWR(
    lat != null && lon != null ? ['nearby-stops', lat.toFixed(4), lon.toFixed(4)] : null,
    () => api.nearbyStops(lat as number, lon as number),
    { ...swrOpts, revalidateOnFocus: false },
  )
}

export function useLiveTrip(id: string | null, pos: { lat: number; lon: number } | null) {
  // Rounded so small GPS jitter doesn't refetch; the 20 s interval keeps live arrivals fresh.
  const key = pos ? `${pos.lat.toFixed(4)},${pos.lon.toFixed(4)}` : 'clock'
  return useSWR(id ? ['live', id, key] : null, () => api.tripLive(id as string, pos), {
    ...swrOpts,
    refreshInterval: (d) => (d && d.status !== 'active' ? 0 : 20_000),
    keepPreviousData: true,
  })
}

/** Revalidate every cached Paxen query. */
export const revalidateAll = () => globalMutate(() => true)

/* ---------- active trip (persisted on the phone) ---------- */

export interface ActiveTrip {
  id: string
  commute_id: string
  signature: string
  summary: string
  started_at: string
  forecast_p50: number
}

const tripStore = persisted('paxen.activeTrip')

export const activeTripStore = {
  set: (trip: ActiveTrip | null) => tripStore.set(trip ? JSON.stringify(trip) : null),
}

export function useActiveTrip(): ActiveTrip | null {
  const raw = useSyncExternalStore(tripStore.subscribe, tripStore.get, tripStore.get)
  return useMemo(() => {
    if (!raw) return null
    try {
      return JSON.parse(raw) as ActiveTrip
    } catch {
      return null
    }
  }, [raw])
}
