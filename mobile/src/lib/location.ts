import { useCallback, useEffect, useRef, useState } from 'react'
import * as Location from 'expo-location'

export type GeoState = 'idle' | 'prompt' | 'watching' | 'denied' | 'unavailable'

/** The phone's position while the live trip screen is open. Kept in memory only; sent with live-trip requests,
 *  never stored. Stops as soon as the screen closes. */
export function useGeolocation() {
  const [state, setState] = useState<GeoState>('idle')
  const [pos, setPos] = useState<{ lat: number; lon: number; accuracy: number } | null>(null)
  const sub = useRef<Location.LocationSubscription | null>(null)

  const watch = useCallback(async () => {
    if (sub.current) return
    try {
      sub.current = await Location.watchPositionAsync(
        { accuracy: Location.Accuracy.High, timeInterval: 10_000, distanceInterval: 15 },
        (p) => {
          setState('watching')
          setPos({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy ?? 0 })
        },
      )
    } catch {
      setState('unavailable')
    }
  }, [])

  const start = useCallback(async () => {
    setState('prompt')
    try {
      const { status } = await Location.requestForegroundPermissionsAsync()
      if (status !== 'granted') return setState('denied')
      await watch()
    } catch {
      setState('unavailable')
    }
  }, [watch])

  // If location is already allowed, start without asking again.
  useEffect(() => {
    let cancelled = false
    Location.getForegroundPermissionsAsync()
      .then((r) => {
        if (cancelled) return
        if (r.status === 'granted') watch()
        else if (r.status === 'denied' && !r.canAskAgain) setState('denied')
      })
      .catch(() => {})
    return () => {
      cancelled = true
      sub.current?.remove()
      sub.current = null
    }
  }, [watch])

  return { state, pos, start }
}
