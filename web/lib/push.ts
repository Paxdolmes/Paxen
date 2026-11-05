'use client'

import { api, IS_DEMO } from './api'

/** Web push for alerts. Browsers: Chrome, Edge, Firefox; Safari on iPhone only once Paxen is on the Home Screen. */

export type PushSupport = 'supported' | 'needs-home-screen' | 'unsupported' | 'blocked'

function isIos() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent)
}

function isStandalone() {
  return window.matchMedia?.('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true
}

export function pushSupport(): PushSupport {
  if (typeof window === 'undefined') return 'unsupported'
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
  if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return null
  return navigator.serviceWorker.register('/sw.js')
}

/** Ask permission, subscribe this browser and tell the server. Returns false if the person said no. */
export async function enablePush(): Promise<boolean> {
  if (IS_DEMO) return true
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
  if (!IS_DEMO && 'serviceWorker' in navigator) {
    const reg = await navigator.serviceWorker.getRegistration()
    const sub = await reg?.pushManager.getSubscription()
    await sub?.unsubscribe()
  }
  await api.unsubscribePush()
}
