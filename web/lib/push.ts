'use client'

import { Capacitor } from '@capacitor/core'
import { api, IS_DEMO } from './api'

/** Push for alerts. In the iPhone app: native notifications (APNs, backend/paxen/apns.py). In a browser: web push
 * (Chrome, Edge, Firefox; Safari on iPhone only once Paxen is on the Home Screen). */

export const isNativeApp = () => Capacitor.isNativePlatform()

export type PushSupport = 'supported' | 'needs-home-screen' | 'unsupported' | 'blocked'

function isIos() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent)
}

function isStandalone() {
  return window.matchMedia?.('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true
}

export function pushSupport(): PushSupport {
  if (typeof window === 'undefined') return 'unsupported'
  if (isNativeApp()) return 'supported'
  const hasApis = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  if (isIos() && !isStandalone()) return 'needs-home-screen'
  if (!hasApis) return 'unsupported'
  if (Notification.permission === 'denied') return 'blocked'
  return 'supported'
}

function keyBytes(base64url: string): Uint8Array {
  const pad = '='.repeat((4 - (base64url.length % 4)) % 4)
  const raw = atob((base64url + pad).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

export async function registerWorker() {
  if (typeof window === 'undefined' || isNativeApp() || !('serviceWorker' in navigator)) return null
  return navigator.serviceWorker.register('/sw.js')
}

/** Ask permission, subscribe this browser and tell the server. Returns false if the person said no. */
export async function enablePush(): Promise<boolean> {
  if (IS_DEMO) return true
  if (isNativeApp()) return enableNativePush()
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') return false
  const reg = (await registerWorker())!
  await navigator.serviceWorker.ready
  const { public_key } = await api.pushKey()
  const existing = await reg.pushManager.getSubscription()
  const sub =
    existing ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) as BufferSource }))
  await api.subscribePush(sub.toJSON())
  return true
}

export async function disablePush() {
  if (isNativeApp()) {
    if (!IS_DEMO) await api.setPushToken(null)
    return
  }
  if (!IS_DEMO && 'serviceWorker' in navigator) {
    const reg = await navigator.serviceWorker.getRegistration()
    const sub = await reg?.pushManager.getSubscription()
    await sub?.unsubscribe()
  }
  await api.unsubscribePush()
}

/* ---------- the iPhone app ---------- */

async function enableNativePush(): Promise<boolean> {
  const { PushNotifications } = await import('@capacitor/push-notifications')
  let perm = await PushNotifications.checkPermissions()
  if (perm.receive === 'prompt' || perm.receive === 'prompt-with-rationale') perm = await PushNotifications.requestPermissions()
  if (perm.receive !== 'granted') return false
  const token = await new Promise<string>((resolve, reject) => {
    PushNotifications.addListener('registration', (t) => resolve(t.value))
    PushNotifications.addListener('registrationError', (e) => reject(new Error(e.error || 'Could not register for notifications.')))
    PushNotifications.register().catch(reject)
  })
  await api.setPushToken(`apns:${token}`)
  return true
}

/** In the iPhone app: tapping a notification opens the screen it points to (the Alerts tab). */
export async function initNativePush(open: (url: string) => void) {
  if (!isNativeApp()) return
  const { PushNotifications } = await import('@capacitor/push-notifications')
  await PushNotifications.addListener('pushNotificationActionPerformed', (a) => {
    const url = (a.notification.data as { url?: string } | undefined)?.url
    if (url) open(url)
  })
}
