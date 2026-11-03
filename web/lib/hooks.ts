'use client'

import { useMemo, useSyncExternalStore } from 'react'
import useSWR, { mutate as globalMutate } from 'swr'
import { api, tokenStore } from './api'
import type { Preference } from './types'

export function useToken() {
  return useSyncExternalStore(
    tokenStore.subscribe,
    () => tokenStore.get(),
    () => undefined as string | null | undefined,
  )
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

/** Revalidate every cached Paxen query. */
export const revalidateAll = () => globalMutate(() => true)

/* ---------- active trip (persisted) ---------- */

const TRIP_KEY = 'paxen.activeTrip'
const tripListeners = new Set<() => void>()

export interface ActiveTrip {
  id: string
  commute_id: string
  signature: string
  summary: string
  started_at: string
  forecast_p50: number
}

export const activeTripStore = {
  get(): string | null {
    try {
      return window.localStorage.getItem(TRIP_KEY)
    } catch {
      return null
    }
  },
  set(trip: ActiveTrip | null) {
    if (trip) window.localStorage.setItem(TRIP_KEY, JSON.stringify(trip))
    else window.localStorage.removeItem(TRIP_KEY)
    tripListeners.forEach((l) => l())
  },
  subscribe(cb: () => void) {
    tripListeners.add(cb)
    return () => tripListeners.delete(cb)
  },
}

export function useActiveTrip(): ActiveTrip | null {
  const raw = useSyncExternalStore(
    activeTripStore.subscribe,
    () => activeTripStore.get(),
    () => null,
  )
  return useMemo(() => {
    if (!raw) return null
    try {
      return JSON.parse(raw) as ActiveTrip
    } catch {
      return null
    }
  }, [raw])
}
