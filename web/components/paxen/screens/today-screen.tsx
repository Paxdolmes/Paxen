'use client'

import { greeting } from '@/lib/format'
import type { Dashboard } from '@/lib/types'
import { Button } from '../primitives/button'
import { Card, Section, Skeleton } from '../primitives/card'
import { ErrorState } from '../primitives/states'
import { Text } from '../primitives/text'
import { CommuteHero } from '../today/commute-hero'
import { ConditionsStrip, UpcomingCard } from '../today/conditions'
import { LinesOnRoutes, OtherCommuteCard } from '../today/secondary-cards'
import type { useNav } from '../use-nav'

export function TodayScreen({
  dashboard,
  error,
  onRetry,
  nav,
}: {
  dashboard: Dashboard | undefined
  error: unknown
  onRetry: () => void
  nav: ReturnType<typeof useNav>
}) {
  if (!dashboard) return error ? <ErrorState error={error} onRetry={onRetry} /> : <TodaySkeleton />

  const active =
    dashboard.commutes.find((c) => c.commute.id === dashboard.active_commute_id) ?? dashboard.commutes[0]
  const others = dashboard.commutes.filter((c) => c !== active)
  const onRoutes = dashboard.network.filter((l) => l.on_my_routes)
  const openRoutes = (id: string) => nav.go('routes', { commute: id })

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1 px-1">
        <Text variant="title1" as="h1">
          {greeting(dashboard.user.name)}
        </Text>
        {dashboard.user.monitoring_paused && (
          <Text variant="subhead" tone="watch">
            Monitoring is paused. You won&apos;t get alerts until you resume it.
          </Text>
        )}
      </div>

      {active && (
        <CommuteHero
          evaluation={active}
          onCompare={() => openRoutes(active.commute.id)}
          onLive={() => nav.go('today', { live: '1' })}
        />
      )}

      {active && <ConditionsStrip conditions={active.conditions} />}

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
            <Button variant="ghost" size="sm" onClick={() => nav.go('network')}>
              All lines
            </Button>
          }
        >
          <LinesOnRoutes lines={onRoutes} />
        </Section>
      )}

      {error ? (
        <Text variant="footnote" tone="attention" className="px-1" role="status">
          Couldn&apos;t refresh just now. Showing the last update.
        </Text>
      ) : null}
    </div>
  )
}

function TodaySkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Loading your commute">
      <Skeleton className="h-8 w-48" />
      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 bg-px-surface-sunken/60 p-5">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </div>
        <div className="flex flex-col gap-4 p-5">
          <Skeleton className="h-12 w-40" />
          <Skeleton className="h-4 w-56" />
          <Skeleton className="h-7 w-full" />
          <Skeleton className="h-14 w-full rounded-px-md" />
        </div>
      </Card>
      <Skeleton className="h-20 w-full rounded-px-lg" />
    </div>
  )
}
