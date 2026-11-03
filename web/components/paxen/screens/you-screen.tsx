'use client'

import { useDashboard } from '@/lib/hooks'
import { Skeleton } from '../primitives/card'
import { ErrorState } from '../primitives/states'
import { Text } from '../primitives/text'
import { AlertSettings } from '../you/alert-settings'
import { CommuteSettings } from '../you/commute-settings'
import { InsightsSection } from '../you/insights-section'
import { PrivacySection } from '../you/privacy-section'
import { SimulatorSection } from '../you/simulator-section'

export function YouScreen() {
  const { data, error, isLoading, mutate } = useDashboard()

  if (error && !data) return <ErrorState error={error} onRetry={() => mutate()} />
  if (isLoading || !data)
    return (
      <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading settings">
        <Skeleton className="h-8 w-24" />
        <Skeleton className="h-40 w-full rounded-px-lg" />
        <Skeleton className="h-56 w-full rounded-px-lg" />
      </div>
    )

  return (
    <div className="flex flex-col gap-8">
      <Text variant="title1" as="h1" className="px-1">
        {data.user.name ? data.user.name : 'You'}
      </Text>
      <CommuteSettings commutes={data.commutes.map((c) => c.commute)} />
      <AlertSettings user={data.user} />
      <InsightsSection />
      <PrivacySection />
      {data.simulated && <SimulatorSection />}
    </div>
  )
}
