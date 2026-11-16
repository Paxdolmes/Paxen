import { Platform } from 'react-native'
import * as Notifications from 'expo-notifications'
import { api } from './api'
import { routeFor } from './links'

// Native alerts through Apple's push service (backend/paxen/apns.py). The server stores the device token as
// "apns:<hex>" and sends alerts to it; turning notifications off clears it.

export type PushPermission = 'granted' | 'denied' | 'undetermined' | 'unsupported'

export async function pushPermission(): Promise<PushPermission> {
  if (Platform.OS === 'web') return 'unsupported'
  const { status } = await Notifications.getPermissionsAsync()
  return status === 'granted' ? 'granted' : status === 'denied' ? 'denied' : 'undetermined'
}

async function register() {
  const { data } = await Notifications.getDevicePushTokenAsync()
  await api.setPushToken(`apns:${data}`)
}

/** Asks for permission (once) and registers this phone. False if the person didn't allow notifications. */
export async function enablePush(): Promise<boolean> {
  if (Platform.OS === 'web') return false
  const { status } = await Notifications.requestPermissionsAsync({ ios: { allowAlert: true, allowBadge: true, allowSound: true } })
  if (status !== 'granted') return false
  await register()
  return true
}

export async function disablePush() {
  await api.setPushToken(null)
}

export interface PushHandlers {
  open: (route: string) => void
  /** "Start trip" on a commute notification. */
  startTrip: (commuteId: string) => void
  /** "Not commuting today". */
  away: () => void
  /** A notification arrived while the app is open. */
  onReceive?: () => void
}

type PushData = { url?: string; commute_id?: string | null } | undefined

/** The buttons on commute notifications (the server marks those with the "commute" category). */
function registerButtons() {
  return Notifications.setNotificationCategoryAsync('commute', [
    { identifier: 'start', buttonTitle: 'Start trip', options: { opensAppToForeground: true } },
    { identifier: 'routes', buttonTitle: 'Show routes', options: { opensAppToForeground: true } },
    { identifier: 'away', buttonTitle: 'Not commuting today', options: { opensAppToForeground: false, isDestructive: true } },
  ]).catch(() => {})
}

function respond(r: Notifications.NotificationResponse | null | undefined, h: PushHandlers) {
  if (!r) return
  const data = r.notification.request.content.data as PushData
  const commute = data?.commute_id ?? null
  if (r.actionIdentifier === 'away') return h.away()
  if (r.actionIdentifier === 'start' && commute) return h.startTrip(commute)
  if (r.actionIdentifier === 'routes' && commute) return h.open(`/routes?commute=${commute}`)
  const route = routeFor(data?.url)
  if (route) h.open(route)
}

/** Shows alerts while the app is open, acts on taps and buttons, and keeps the token fresh. */
export function initPush(h: PushHandlers, signedIn: boolean) {
  if (Platform.OS === 'web') return () => {}
  Notifications.setNotificationHandler({
    handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
  })
  void registerButtons()
  let handled: string | null = null // the response that launched the app also reaches the listener: act once
  const once = (r: Notifications.NotificationResponse | null | undefined) => {
    const id = r ? `${r.notification.request.identifier}:${r.actionIdentifier}` : null
    if (!id || id === handled) return
    handled = id
    respond(r, h)
  }
  const sub = Notifications.addNotificationResponseReceivedListener(once)
  // An alert that arrives while the app is open: bring the screens up to date with it.
  const got = Notifications.addNotificationReceivedListener(() => h.onReceive?.())
  if (signedIn) {
    Notifications.getLastNotificationResponseAsync()
      .then((r) => {
        once(r)
        if (r) return Notifications.clearLastNotificationResponseAsync()
      })
      .catch(() => {})
    // Apple can change a device's token; re-send it whenever the app starts with notifications allowed.
    pushPermission()
      .then((s) => (s === 'granted' ? register() : undefined))
      .catch(() => {})
  }
  return () => {
    sub.remove()
    got.remove()
  }
}
