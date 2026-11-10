import { View } from 'react-native'
import { useDashboard } from '@/lib/hooks'
import { Screen } from '@/components/screen'
import { ErrorState, Skeleton } from '@/components/ui'
import { AlertSettings, AutoTripsSection, CommuteSettings, InsightsSection, PrivacySection, SimulatorSection } from '@/components/you'

export default function YouScreen() {
  const { data, error, isLoading, mutate } = useDashboard()

  if (error && !data)
    return (
      <Screen title="You">
        <ErrorState error={error} onRetry={() => mutate()} />
      </Screen>
    )
  if (isLoading || !data)
    return (
      <Screen title="You">
        <View style={{ gap: 16 }}>
          <Skeleton style={{ height: 160, borderRadius: 20 }} />
          <Skeleton style={{ height: 224, borderRadius: 20 }} />
        </View>
      </Screen>
    )

  return (
    <Screen title={data.user.name || 'You'} gap={32} onRefresh={() => mutate()}>
      <CommuteSettings commutes={data.commutes.map((c) => c.commute)} />
      <AutoTripsSection user={data.user} />
      <AlertSettings user={data.user} />
      <InsightsSection />
      <PrivacySection />
      {data.simulated && <SimulatorSection />}
    </Screen>
  )
}
