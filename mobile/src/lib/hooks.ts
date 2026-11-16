import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import useSWR, { mutate as globalMutate } from 'swr'
import type { Dashboard, Preference } from '@/shared/types'
import { api, tokenStore } from './api'
import { persisted } from './storage'

export function useToken() {
  return useSyncExternalStore(tokenStore.subscribe, tokenStore.get, tokenStore.get)
}

const swrOpts = { revalidateOnFocus: true, shouldRetryOnError: false } as const

/* The last Today data is kept on the phone, so opening the app shows it at once while fresh data loads. */
const dashStore = persisted('paxen.dashboard')
const DASH_KEEP_MS = 30 * 60_000 // older than this is no use for a commute: show the loading state instead
const who = (token: string | null | undefined) => (token ? token.slice(-12) : '')

async function fetchDashboard() {
  const data = await api.dashboard()
  dashStore.set(JSON.stringify({ who: who(tokenStore.get()), at: Date.now(), data }))
  return data
}

function savedDashboard(raw: string | null | undefined, token: string | null | undefined): Dashboard | undefined {
  if (!raw || !token) return undefined
  try {
    const saved = JSON.parse(raw) as { who: string; at: number; data: Dashboard }
    return saved.who === who(token) && Date.now() - saved.at < DASH_KEEP_MS ? saved.data : undefined
  } catch {
    return undefined
  }
}

export function useDashboard(enabled = true) {
  const token = useToken()
  const raw = useSyncExternalStore(dashStore.subscribe, dashStore.get, dashStore.get)
  const saved = useMemo(() => savedDashboard(raw, token), [raw, token])
  // Wait for the saved copy to be read (a few milliseconds) so the first render can use it.
  return useSWR(enabled && raw !== undefined ? ['dashboard'] : null, fetchDashboard, {
    ...swrOpts,
    refreshInterval: 60_000,
    keepPreviousData: true,
    fallbackData: saved,
    revalidateOnMount: true,
  })
}

/** The time now, re-read every `everyMs` so countdowns keep moving between refreshes. */
export function useNow(everyMs = 20_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs)
    return () => clearInterval(id)
  }, [everyMs])
  return now
}

export function useCompare(commuteId: string | null | undefined, preference: Preference | undefined, departAt?: string | null) {
  return useSWR(commuteId ? ['compare', commuteId, preference ?? '', departAt ?? ''] : null, () => api.compare(commuteId!, preference, departAt), {
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
