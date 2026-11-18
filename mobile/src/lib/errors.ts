import { Platform } from 'react-native'

// In a release build React Native closes the app on any JavaScript error that nothing caught ("Unhandled JS
// Exception"). This file is loaded first (index.ts): errors outside React (timers, callbacks, promises) are reported
// and the app carries on; errors while drawing a screen are caught by the boundaries in components/boundary.tsx.
//
// Reports go to the server (POST /v1/app-errors) with technical details only: the error, where in the code, the
// build. Never the account, a place or a position.

export type ErrorKind = 'fatal' | 'error' | 'screen' | 'card' | 'promise'

const sent = new Set<string>()

export function reportError(error: unknown, kind: ErrorKind, componentStack?: string | null): void {
  try {
    const e = error instanceof Error ? error : new Error(typeof error === 'string' ? error : 'Non-error thrown')
    const message = `${e.name}: ${e.message}`.slice(0, 1000)
    const key = `${kind}|${message}`
    if (sent.has(key) || sent.size >= 25) return // once per error and session, and never a flood
    sent.add(key)
    const stack = [String(e.stack ?? ''), componentStack ? `component stack:${componentStack}` : '']
      .filter(Boolean)
      .join('\n')
      .slice(0, 8000)
    // Required here rather than imported: this file has to load before everything else and can never fail to.
    /* eslint-disable @typescript-eslint/no-require-imports */
    const { API_BASE } = require('./api') as typeof import('./api')
    const Constants = (require('expo-constants') as typeof import('expo-constants')).default
    /* eslint-enable @typescript-eslint/no-require-imports */
    const build = Constants.expoConfig?.ios?.buildNumber ?? Constants.expoConfig?.version ?? null
    fetch(`${API_BASE}/v1/app-errors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, message, stack, build: build ? String(build) : null, platform: Platform.OS }),
    }).catch(() => {})
  } catch {
    // reporting is best effort
  }
}

type Handler = (error: unknown, isFatal?: boolean) => void
type Globals = {
  ErrorUtils?: { getGlobalHandler(): Handler; setGlobalHandler(h: Handler): void }
  HermesInternal?: { enablePromiseRejectionTracker?: (o: { allRejections: boolean; onUnhandled: (id: number, e: unknown) => void }) => void }
}

let ours: Handler | null = null

/** Catch what React Native would otherwise close the app over. Safe to call more than once. */
export function installErrorHandler(): void {
  if (Platform.OS === 'web') return
  const g = globalThis as unknown as Globals
  const eu = g.ErrorUtils
  if (!eu || (ours && eu.getGlobalHandler() === ours)) return
  const previous = eu.getGlobalHandler()
  ours = (error, isFatal) => {
    reportError(error, isFatal ? 'fatal' : 'error')
    // Not fatal: React Native only logs it. Fatal: it would close the app, so it stops here and the app carries on.
    if (__DEV__ || !isFatal) previous?.(error, isFatal)
  }
  eu.setGlobalHandler(ours)
  if (__DEV__) return // (in development React Native shows these itself)
  try {
    g.HermesInternal?.enablePromiseRejectionTracker?.({
      allRejections: false,
      onUnhandled: (_id, e) => reportError(e, 'promise'),
    })
  } catch {
    // not Hermes
  }
}

installErrorHandler()
