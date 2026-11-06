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

/** Shows alerts while the app is open, opens the right screen when one is tapped, and keeps the token fresh. */
export function initPush(open: (route: string) => void, signedIn: boolean) {
  if (Platform.OS === 'web') return () => {}
  Notifications.setNotificationHandler({
    handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }),
  })
  const sub = Notifications.addNotificationResponseReceivedListener((r) => {
    const route = routeFor((r.notification.request.content.data as { url?: string } | undefined)?.url)
    if (route) open(route)
  })
  Notifications.getLastNotificationResponseAsync()
    .then((r) => {
      const route = routeFor((r?.notification.request.content.data as { url?: string } | undefined)?.url)
      if (route) open(route)
    })
    .catch(() => {})
  // Apple can change a device's token; re-send it whenever the app starts with notifications allowed.
  if (signedIn) pushPermission()
      .then((s) => (s === 'granted' ? register() : undefined))
      .catch(() => {})
  return () => sub.remove()
}
