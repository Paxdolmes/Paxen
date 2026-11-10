import { View } from 'react-native'
import { router } from 'expo-router'
import { greeting } from '@/shared/format'
import { useDashboard } from '@/lib/hooks'
import { Screen } from '@/components/screen'
import { Text } from '@/components/text'
import { AutoTripsNudge, CommuteHero, ConditionsStrip, LinesOnRoutes, OtherCommuteCard, UpcomingCard } from '@/components/today'
import { Button, Card, ErrorState, Section, Skeleton } from '@/components/ui'

export default function TodayScreen() {
  const { data: dashboard, error, mutate } = useDashboard()
  const openRoutes = (id: string) => router.navigate({ pathname: '/routes', params: { commute: id } })

  if (!dashboard)
    return (
      <Screen onRefresh={() => mutate()}>
        {error ? <ErrorState error={error} onRetry={() => mutate()} /> : <TodaySkeleton />}
      </Screen>
    )

  const active = dashboard.commutes.find((c) => c.commute.id === dashboard.active_commute_id) ?? dashboard.commutes[0]
  const others = dashboard.commutes.filter((c) => c !== active)
  const onRoutes = dashboard.network.filter((l) => l.on_my_routes)

  return (
    <Screen onRefresh={() => mutate()}>
      <View style={{ gap: 4, paddingHorizontal: 4 }}>
        <Text variant="title1" accessibilityRole="header">
          {greeting(dashboard.user.name)}
        </Text>
        {dashboard.user.monitoring_paused && (
          <Text variant="subhead" tone="watch">
            Monitoring is paused. You won&apos;t get alerts until you resume it.
          </Text>
        )}
      </View>

      {active && <CommuteHero evaluation={active} onCompare={() => openRoutes(active.commute.id)} />}
      {active && <ConditionsStrip conditions={active.conditions} />}

      <AutoTripsNudge enabled={!!dashboard.user.auto_trips} />

      {(dashboard.upcoming?.length ?? 0) > 0 && (
        <Section title="Coming up on your lines">
          <UpcomingCard items={dashboard.upcoming ?? []} />
        </Section>
      )}

      {others.length > 0 && (
        <Section title="Your other commute">
          {others.map((c) => (
            <OtherCommuteCard key={c.commute.id} evaluation={c} onOpen={() => openRoutes(c.commute.id)} />
          ))}
        </Section>
      )}

      {onRoutes.length > 0 && (
        <Section
          title="Lines on your routes"
          action={
            <Button variant="ghost" size="sm" onPress={() => router.navigate('/network')}>
              All lines
            </Button>
          }
        >
          <LinesOnRoutes lines={onRoutes} />
        </Section>
      )}

      {error ? (
        <Text variant="footnote" tone="attention" style={{ paddingHorizontal: 4 }}>
          Couldn&apos;t refresh just now. Showing the last update.
        </Text>
      ) : null}
    </Screen>
  )
}

function TodaySkeleton() {
  return (
    <View style={{ gap: 24 }} accessibilityLabel="Loading your commute">
      <Skeleton style={{ height: 32, width: 192 }} />
      <Card style={{ padding: 20, gap: 16 }}>
        <Skeleton style={{ height: 16, width: 128 }} />
        <Skeleton style={{ height: 32 }} />
        <Skeleton style={{ height: 48, width: 160 }} />
        <Skeleton style={{ height: 56 }} />
      </Card>
      <Skeleton style={{ height: 80, borderRadius: 20 }} />
    </View>
  )
}
