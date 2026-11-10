import { Platform } from 'react-native'
import * as Location from 'expo-location'
import * as TaskManager from 'expo-task-manager'
import { api } from './api'
import { persisted } from './storage'

// Automatic trips. With it on, iOS watches an area around Home and Work (region monitoring: low power, and it wakes
// the app briefly in the background even when it's closed). Each crossing is sent as "left/reached <place> at
// <time>", never a position; the server pairs them into trips and keeps only believable ones (backend autotrips.py).

export const GEOFENCE_TASK = 'paxen-commute-geofences'
export const RADIUS_M = 150 // keep in step with GEOFENCE_RADIUS_M in backend/paxen/autotrips.py

type Crossing = { place_id: string; event: 'enter' | 'exit'; at: string }

// Crossings that couldn't be sent (no signal on the platform...) wait here and go with the next one.
const queue = persisted('paxen.tripEvents')

function queued(): Crossing[] {
  try {
    return JSON.parse(queue.get() ?? '[]') as Crossing[]
  } catch {
    return []
  }
}

export async function flushCrossings(extra?: Crossing) {
  await queue.ready
  const all = [...queued(), ...(extra ? [extra] : [])].slice(-20)
  const left: Crossing[] = []
  for (const c of all) {
    try {
      await api.tripEvent(c.place_id, c.event, c.at)
    } catch {
      left.push(c)
    }
  }
  queue.set(left.length ? JSON.stringify(left) : null)
}

// Must be defined when the JavaScript starts, so it's imported by the app's entry file (index.ts): iOS can start
// the app in the background just to run it.
if (Platform.OS !== 'web') {
  TaskManager.defineTask(GEOFENCE_TASK, async ({ data, error }) => {
    if (error || !data) return
    const { eventType, region } = data as { eventType: Location.GeofencingEventType; region: Location.LocationRegion }
    if (!region?.identifier) return
    const event = eventType === Location.GeofencingEventType.Enter ? 'enter' : 'exit'
    await flushCrossings({ place_id: region.identifier, event, at: new Date().toISOString() })
  })
}

export type AutoTripsState = 'on' | 'off' | 'needs-always' | 'denied' | 'unsupported'

/** Watch Home and Work again (after a place changes, or when the app starts). */
export async function syncGeofences(): Promise<boolean> {
  if (Platform.OS === 'web') return false
  const places = await api.places()
  const regions = places
    .filter((p) => p.label === 'home' || p.label === 'work')
    .map((p) => ({ identifier: p.id, latitude: p.lat, longitude: p.lon, radius: RADIUS_M, notifyOnEnter: true, notifyOnExit: true }))
  if (!regions.length) return false
  await Location.startGeofencingAsync(GEOFENCE_TASK, regions) // replaces the areas watched before
  return true
}

/** Asks for location "Always" (needed for areas to be watched in the background), then turns it on. */
export async function enableAutoTrips(): Promise<AutoTripsState> {
  if (Platform.OS === 'web') return 'unsupported'
  const fg = await Location.requestForegroundPermissionsAsync()
  if (fg.status !== 'granted') return 'denied'
  const bg = await Location.requestBackgroundPermissionsAsync()
  if (bg.status !== 'granted') return 'needs-always'
  await syncGeofences()
  await api.patchMe({ auto_trips: true })
  return 'on'
}

export async function disableAutoTrips() {
  if (Platform.OS !== 'web' && (await Location.hasStartedGeofencingAsync(GEOFENCE_TASK).catch(() => false))) {
    await Location.stopGeofencingAsync(GEOFENCE_TASK)
  }
  await api.patchMe({ auto_trips: false })
}

/** What the phone allows right now, for the settings screen. */
export async function autoTripsPermission(): Promise<'always' | 'when-in-use' | 'denied' | 'undetermined' | 'unsupported'> {
  if (Platform.OS === 'web') return 'unsupported'
  const bg = await Location.getBackgroundPermissionsAsync()
  if (bg.status === 'granted') return 'always'
  const fg = await Location.getForegroundPermissionsAsync()
  if (fg.status === 'granted') return 'when-in-use'
  return fg.status === 'denied' ? 'denied' : 'undetermined'
}

/** On app start: if the user has it on and the phone allows it, make sure the areas are watched and send anything queued. */
export async function resumeAutoTrips(enabled: boolean) {
  if (Platform.OS === 'web' || !enabled) return
  if ((await autoTripsPermission()) !== 'always') return
  await syncGeofences().catch(() => {})
  await flushCrossings().catch(() => {})
}
