'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

export type GeoState = 'idle' | 'prompt' | 'watching' | 'denied' | 'unavailable'

/** Phone position while the app is open. Kept in memory only; sent with live-trip requests, never stored. */
export function useGeolocation() {
  const [state, setState] = useState<GeoState>('idle')
  const [pos, setPos] = useState<{ lat: number; lon: number; accuracy: number } | null>(null)
  const watchId = useRef<number | null>(null)

  const start = useCallback(() => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setState('unavailable')
      return
    }
    if (watchId.current != null) return
    setState('prompt')
    watchId.current = navigator.geolocation.watchPosition(
      (p) => {
        setState('watching')
        setPos({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy })
      },
      (err) => setState(err.code === err.PERMISSION_DENIED ? 'denied' : 'unavailable'),
      { enableHighAccuracy: true, maximumAge: 15_000, timeout: 20_000 },
    )
  }, [])

  // If the user already allowed location for Paxen, start without asking again.
  useEffect(() => {
    let cancelled = false
    navigator.permissions
      ?.query({ name: 'geolocation' as PermissionName })
      .then((r) => {
        if (!cancelled && r.state === 'granted') start()
        if (!cancelled && r.state === 'denied') setState('denied')
      })
      .catch(() => {})
    return () => {
      cancelled = true
      if (watchId.current != null) navigator.geolocation.clearWatch(watchId.current)
      watchId.current = null
    }
  }, [start])

  return { state, pos, start }
}
