import type { EventSubscription } from 'expo'
import type { LiveActivity, LiveActivityFactory, Widget } from 'expo-widgets'
import { api } from './api'
import type { ActivityProps, WidgetProps } from './surface-data'

// The trip on the lock screen (a Live Activity) and the home-screen widget. Both are extras: every call is guarded,
// because Live Activities can be switched off in Settings and a build may not include the widget extension.

const STALE_MS = 5 * 60_000 // iOS greys the times if nothing refreshes them for this long

// Loaded on first use, never at startup: registering a layout talks to the widget extension's shared storage, and
// a build without the extension must start exactly as before. A failure here is remembered and never retried.
type Surfaces = { trip: LiveActivityFactory<ActivityProps>; widget: Widget<WidgetProps>; after: (date: Date) => { after: Date } }
let surfaces: Surfaces | null | undefined

function load(): Surfaces {
  if (surfaces === undefined) {
    try {
      /* eslint-disable @typescript-eslint/no-require-imports */
      surfaces = {
        trip: require('@/widgets/trip-activity').default,
        widget: require('@/widgets/commute-widget').default,
        after: require('expo-widgets').after,
      }
      /* eslint-enable @typescript-eslint/no-require-imports */
    } catch {
      surfaces = null
    }
  }
  if (!surfaces) throw new Error('widgets are not in this build')
  return surfaces
}

let current: { tripId: string; instance: LiveActivity<ActivityProps>; token: string | null; shown: string; sub?: EventSubscription } | null = null

function attach(tripId: string, instance: LiveActivity<ActivityProps>, shown: string) {
  const mine = { tripId, instance, token: null as string | null, shown, sub: undefined as EventSubscription | undefined }
  // The server keeps the lock screen up to date through this token once the app is closed.
  const send = (token: string | null) => {
    if (!token || current !== mine || token === mine.token) return
    mine.token = token
    api.tripActivity(tripId, token).catch(() => {})
  }
  instance.getPushToken().then(send).catch(() => {})
  mine.sub = instance.addPushTokenListener((e) => send(e.pushToken))
  current = mine
}

/** Show this trip on the lock screen, or bring what's showing up to date. */
export function syncTripActivity(tripId: string, props: ActivityProps): void {
  try {
    const shown = JSON.stringify(props)
    if (current && current.tripId !== tripId) void endTripActivity()
    const stale = new Date(Date.now() + STALE_MS)
    if (!current) {
      const { trip } = load()
      const [existing, ...extra] = trip.getInstances() // one may have outlived the app
      extra.forEach((i) => void i.end('immediate').catch(() => {}))
      if (existing) {
        attach(tripId, existing, shown)
        void existing.update(props, stale).catch(() => {})
      } else attach(tripId, trip.start(props, 'paxen://live', stale), shown)
    } else if (current.shown !== shown) {
      current.shown = shown
      void current.instance.update(props, stale).catch(() => {})
    }
  } catch {
    // not available here: the app works the same without it
  }
}

/** The trip is over: leave the result on the lock screen for ten minutes, or clear it at once. */
export async function endTripActivity(final?: ActivityProps): Promise<void> {
  try {
    const mine = current
    current = null
    mine?.sub?.remove()
    const { trip, after } = load()
    const instances = mine ? [mine.instance] : trip.getInstances()
    await Promise.all(
      instances.map((i) => (final ? i.end(after(new Date(Date.now() + 10 * 60_000)), final) : i.end('immediate')).catch(() => {})),
    )
    if (mine?.token) api.tripActivity(mine.tripId, null).catch(() => {})
  } catch {
    // nothing was showing
  }
}

let lastWidget = ''

export function updateCommuteWidget(entries: { at: number; props: WidgetProps }[]): void {
  try {
    if (!entries.length) return
    const key = JSON.stringify(entries)
    if (key === lastWidget) return
    lastWidget = key
    load().widget.updateTimeline(entries.map((e) => ({ date: new Date(e.at), props: e.props })))
  } catch {
    // no widget extension in this build
  }
}
