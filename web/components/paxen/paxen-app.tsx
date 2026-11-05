'use client'

import { useEffect, useRef, useState } from 'react'
import { IS_DEMO } from '@/lib/api'
import { revalidateAll, useActiveTrip, useDashboard, useToken } from '@/lib/hooks'
import { registerWorker } from '@/lib/push'
import { AppHeader, Wordmark } from './app-header'
import { AlertsScreen } from './screens/alerts-screen'
import { NetworkScreen } from './screens/network-screen'
import { OnboardingScreen } from './screens/onboarding-screen'
import { RoutesScreen } from './screens/routes-screen'
import { TodayScreen } from './screens/today-screen'
import { YouScreen } from './screens/you-screen'
import { TabBar } from './tab-bar'
import { LiveTripScreen } from './trip/live-trip-screen'
import { useNav } from './use-nav'

function Splash() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-px-canvas" aria-busy="true">
      <Wordmark size={32} />
      <span className="sr-only">Loading Paxen</span>
    </main>
  )
}

export function PaxenApp() {
  const token = useToken()
  const [onboarding, setOnboarding] = useState(false)
  const nav = useNav()
  const signedIn = !!token && !onboarding
  const { data: dashboard, error, mutate } = useDashboard(signedIn)
  const mainRef = useRef<HTMLElement>(null)
  const activeTrip = useActiveTrip()

  useEffect(() => {
    // keep the notification worker current once someone has allowed notifications
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') registerWorker().catch(() => {})
  }, [])

  useEffect(() => {
    window.scrollTo({ top: 0 })
    mainRef.current?.focus({ preventScroll: true })
  }, [nav.tab])

  if (token === undefined) return <Splash />

  const needsOnboarding = token === null || onboarding || (dashboard && dashboard.commutes.length === 0)
  if (needsOnboarding)
    return (
      <OnboardingScreen
        onStart={() => setOnboarding(true)}
        onDone={async () => {
          setOnboarding(false)
          await revalidateAll()
          nav.go('today', {}, { replace: true })
        }}
      />
    )

  if (nav.live && activeTrip)
    return <LiveTripScreen active={activeTrip} onClose={() => nav.go(nav.tab, { live: null })} />

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-[430px] flex-col bg-px-canvas">
      <AppHeader demo={IS_DEMO} simulated={!!dashboard?.simulated} />
      <main
        ref={mainRef}
        tabIndex={-1}
        className="flex flex-1 flex-col px-5 pb-28 pt-2 outline-none"
        aria-label={nav.tab}
      >
        {nav.tab === 'today' && <TodayScreen dashboard={dashboard} error={error} onRetry={() => mutate()} nav={nav} />}
        {nav.tab === 'routes' && <RoutesScreen dashboard={dashboard} nav={nav} />}
        {nav.tab === 'network' && <NetworkScreen />}
        {nav.tab === 'alerts' && <AlertsScreen />}
        {nav.tab === 'you' && <YouScreen />}
      </main>
      <TabBar active={nav.tab} unread={dashboard?.unread_alerts ?? 0} onSelect={(t) => nav.go(t)} />
    </div>
  )
}
