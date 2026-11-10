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
import { revalidateAll, useToken } from '@/lib/hooks'
import { initPush } from '@/lib/push'

void SplashScreen.preventAutoHideAsync().catch(() => {})

// Live data refreshes on a timer while the app is in front, and straight away when you come back to it.
const swrConfig = { isOnline: () => true, isVisible: () => AppState.currentState === 'active' }

export default function RootLayout() {
  const scheme = useColorScheme() === 'dark' ? 'dark' : 'light'
  const p = palettes[scheme]
  const token = useToken()
  const [fontsLoaded, fontError] = useFonts(fonts)
  const fontsReady = fontsLoaded || !!fontError // without the font the wordmark falls back to the system face

  useEffect(() => {
    if (token !== undefined && fontsReady) void SplashScreen.hideAsync().catch(() => {})
  }, [token, fontsReady])

  useEffect(() => initPush((route) => router.push(route as never), !!token), [token])

  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => next === 'active' && revalidateAll())
    return () => sub.remove()
  }, [])

  const base = scheme === 'dark' ? DarkTheme : DefaultTheme
  const theme = { ...base, colors: { ...base.colors, primary: p.brand, background: p.canvas, card: p.surface, text: p.text, border: p.border } }

  return (
    <SafeAreaProvider>
      <SWRConfig value={swrConfig}>
        <ThemeProvider value={theme}>
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: p.canvas } }}>
            <Stack.Screen name="(tabs)" />
            <Stack.Screen name="onboarding" options={{ gestureEnabled: false, animation: 'fade' }} />
            <Stack.Screen name="live" options={{ presentation: 'fullScreenModal' }} />
          </Stack>
          <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
        </ThemeProvider>
      </SWRConfig>
    </SafeAreaProvider>
  )
}
