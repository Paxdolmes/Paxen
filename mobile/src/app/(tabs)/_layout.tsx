import { useEffect } from 'react'
import { ActivityIndicator, View } from 'react-native'
import { Redirect, Tabs } from 'expo-router'
import { Activity, Bell, Route, Sun, UserRound } from 'lucide-react-native'
import { resumeAutoTrips } from '@/lib/autotrips'
import { useDashboard, useToken } from '@/lib/hooks'
import { usePalette } from '@/lib/theme'

export default function TabsLayout() {
  const p = usePalette()
  const token = useToken()
  const { data: dashboard, error } = useDashboard(!!token)
  const autoTrips = !!dashboard?.user.auto_trips
  useEffect(() => {
    resumeAutoTrips(autoTrips).catch(() => {})
  }, [autoTrips])

  if (token === undefined || (token && !dashboard && !error)) {
    return (
      <View style={{ flex: 1, backgroundColor: p.canvas, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color={p.brand} />
      </View>
    )
  }
  // New phone, ended session, or an account with no commute yet: set up first.
  if (!token || (dashboard && dashboard.commutes.length === 0)) return <Redirect href="/onboarding" />

  const unread = dashboard?.unread_alerts ?? 0
  const icon = (I: typeof Sun) =>
    function TabIcon({ color, focused }: { color: unknown; focused: boolean }) {
      return <I size={24} color={String(color)} strokeWidth={focused ? 2.25 : 1.75} />
    }

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: p.brand,
        tabBarInactiveTintColor: p.textTertiary,
        tabBarStyle: { backgroundColor: p.surface, borderTopColor: p.border },
        tabBarLabelStyle: { fontSize: 12, fontWeight: '600' },
        sceneStyle: { backgroundColor: p.canvas },
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Today', tabBarIcon: icon(Sun) }} />
      <Tabs.Screen name="routes" options={{ title: 'Routes', tabBarIcon: icon(Route) }} />
      <Tabs.Screen name="network" options={{ title: 'Network', tabBarIcon: icon(Activity) }} />
      <Tabs.Screen
        name="alerts"
        options={{
          title: 'Alerts',
          tabBarIcon: icon(Bell),
          tabBarBadge: unread > 0 ? (unread > 9 ? '9+' : unread) : undefined,
          tabBarBadgeStyle: { backgroundColor: p.attention, color: p.onAttention, fontSize: 11, fontWeight: '700' },
        }}
      />
      <Tabs.Screen name="you" options={{ title: 'You', tabBarIcon: icon(UserRound) }} />
    </Tabs>
  )
}
