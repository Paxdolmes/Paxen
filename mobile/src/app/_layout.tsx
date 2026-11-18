import { useEffect } from 'react'
import { AppState, useColorScheme } from 'react-native'
import { DarkTheme, DefaultTheme, Stack, ThemeProvider, router } from 'expo-router'
import { useFonts } from 'expo-font'
import * as SplashScreen from 'expo-splash-screen'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { SWRConfig } from 'swr'
import { palettes } from '@/shared/paxen-tokens'
import { fonts } from '@/lib/fonts'
import { revalidateAll, useActiveTrip, useLiveTrip, useToken } from '@/lib/hooks'
import { endTripActivity, syncTripActivity } from '@/lib/native-surfaces'
import { activityProps } from '@/lib/surface-data'
import { api } from '@/lib/api'
import { initPush } from '@/lib/push'
import { startRecommended } from '@/lib/trip-actions'
import { installErrorHandler, reportError } from '@/lib/errors'
import { Boundary, ScreenNote } from '@/components/boundary'

void SplashScreen.preventAutoHideAsync().catch(() => {})

/** Open a screen from a notification. Safe before the screens are ready: it tries again shortly instead of failing. */
function go(route: string, tries = 0) {
  try {
    router.push(route as never)
  } catch {
    if (tries < 10) setTimeout(() => go(route, tries + 1), 500)
  }
}

// Live data refreshes on a timer while the app is in front, and straight away when you come back to it.
const swrConfig = { isOnline: () => true, isVisible: () => AppState.currentState === 'active' }

/** Keeps the trip on the lock screen (iPhone) in step with the trip in the app. Renders nothing. */
function TripOnLockScreen() {
  const trip = useActiveTrip()
  const { data: live } = useLiveTrip(trip?.id ?? null, null)
  const tripId = trip?.id ?? null
  useEffect(() => {
    if (!tripId) return void endTripActivity()
    if (!live || live.trip_id !== tripId) return
    const props = activityProps(live)
    if (live.status === 'active') syncTripActivity(tripId, props)
    else void endTripActivity(props)
  }, [tripId, live])
  return null
}

export default function RootLayout() {
  const scheme = useColorScheme() === 'dark' ? 'dark' : 'light'
  const p = palettes[scheme]
  const token = useToken()
  const [fontsLoaded, fontError] = useFonts(fonts)
  const fontsReady = fontsLoaded || !!fontError // without the font the wordmark falls back to the system face

  useEffect(() => {
    if (token !== undefined && fontsReady) void SplashScreen.hideAsync().catch(() => {})
  }, [token, fontsReady])

  useEffect(
    () =>
      initPush(
        {
          open: (route) => go(route),
          startTrip: (commuteId) =>
            void startRecommended(commuteId)
              .then((ok) => go(ok ? '/live' : `/routes?commute=${commuteId}`))
              .catch(() => go('/')),
          away: () =>
            void api
              .patchMe({ away_today: true })
              .then(() => revalidateAll())
              .catch(() => {}),
          onReceive: () => void revalidateAll(),
        },
        !!token,
      ),
    [token],
  )

  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => next === 'active' && revalidateAll())
    installErrorHandler() // again, in case a library replaced it while loading
    return () => sub.remove()
  }, [])

  const base = scheme === 'dark' ? DarkTheme : DefaultTheme
  const theme = { ...base, colors: { ...base.colors, primary: p.brand, background: p.canvas, card: p.surface, text: p.text, border: p.border } }

  return (
    <SafeAreaProvider>
      <SWRConfig value={swrConfig}>
        <Boundary level="silent">
          <TripOnLockScreen />
        </Boundary>
        <ThemeProvider value={theme}>
          <Boundary level="screen" onRetry={() => void revalidateAll()}>
            <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: p.canvas } }}>
              <Stack.Screen name="(tabs)" />
              <Stack.Screen name="onboarding" options={{ gestureEnabled: false, animation: 'fade' }} />
              <Stack.Screen name="live" options={{ presentation: 'fullScreenModal' }} />
            </Stack>
          </Boundary>
          <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
        </ThemeProvider>
      </SWRConfig>
    </SafeAreaProvider>
  )
}

/** Expo Router shows this if the layout above fails (the boundaries inside it catch everything else). */
export function ErrorBoundary({ error, retry }: { error: Error; retry: () => Promise<void> }) {
  useEffect(() => reportError(error, 'screen'), [error])
  return <ScreenNote error={error} onRetry={() => void retry()} />
}
