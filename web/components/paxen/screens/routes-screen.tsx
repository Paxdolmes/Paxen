'use client'

import { useMemo, useState } from 'react'
import { mutate } from 'swr'
import { api } from '@/lib/api'
import { fmtMin, PREFERENCE_LABELS, PREFERENCES } from '@/lib/format'
import { useActiveTrip, useCompare } from '@/lib/hooks'
import type { Dashboard, Preference } from '@/lib/types'
import { Card, Skeleton } from '../primitives/card'
import { Segmented } from '../primitives/segmented'
import { ErrorState } from '../primitives/states'
import { Text } from '../primitives/text'
import { OptionCard } from '../routes/option-card'
import { AxisLabels, buildAxis } from '../transit/range-bar'
import { CommuteStatusPill } from '../transit/status'
import { useNav } from '../use-nav'
import { useStartTrip } from '../use-trip-actions'

export function RoutesScreen({ dashboard, nav }: { dashboard: Dashboard | undefined; nav: ReturnType<typeof useNav> }) {
  const commutes = dashboard?.commutes ?? []
  const commuteId =
    (commutes.some((c) => c.commute.id === nav.commute) && nav.commute) ||
    dashboard?.active_commute_id ||
    commutes[0]?.commute.id ||
    null
  const base = commutes.find((c) => c.commute.id === commuteId)
  const pref: Preference = nav.pref ?? base?.commute.preference ?? 'balanced'

  const { data, error, isLoading, mutate: refetch } = useCompare(commuteId, pref)
  const { start, pending, error: startError } = useStartTrip()
  const activeTrip = useActiveTrip()
  const [savingUsual, setSavingUsual] = useState<string | null>(null)
  const [usualError, setUsualError] = useState<string | null>(null)

  const options = data?.options ?? []
  const axis = useMemo(
    () => buildAxis(options.filter((o) => o.feasible).map((o) => o.arrive_range)),
    [options],
  )

  const makeUsual = async (sig: string) => {
    if (!commuteId) return
    setSavingUsual(sig)
    setUsualError(null)
    try {
      await api.setUsual(commuteId, sig)
      await Promise.all([refetch(), mutate(['dashboard'])])
    } catch (e) {
      setUsualError(e instanceof Error ? e.message : 'Could not save your usual route.')
    } finally {
      setSavingUsual(null)
    }
  }

  if (!dashboard) return <RoutesSkeleton />

  return (
    <div className="flex flex-col gap-5">
      <Text variant="title1" as="h1" className="px-1">
        Compare routes
      </Text>

      {commutes.length > 1 && (
        <Segmented
          label="Commute"
          value={commuteId ?? ''}
          options={commutes.map((c) => ({ value: c.commute.id, label: c.commute.name }))}
          onChange={(id) => nav.go('routes', { commute: id, pref: null }, { replace: true })}
        />
      )}

      <Segmented
        label="Route preference"
        scroll
        value={pref}
        options={PREFERENCES.map((p) => ({ value: p, label: PREFERENCE_LABELS[p] }))}
        onChange={(p) => nav.go('routes', { commute: commuteId, pref: p }, { replace: true })}
      />

      {data && (
        <div className="flex flex-col gap-1 px-1">
          <div className="flex items-center gap-2">
            <CommuteStatusPill status={data.status} />
            <Text variant="footnote" tone="secondary" tabular>
              {data.commute.origin.name} → {data.commute.dest.name}
            </Text>
          </div>
          <Text variant="headline" as="h2" className="text-pretty">
            {data.headline}
          </Text>
          <Text variant="footnote" tone="secondary" tabular>
            {data.baseline.p50 != null ? `Normal: ${fmtMin(data.baseline.p50)} · ${data.baseline.label}` : 'Learning your routine'}
          </Text>
        </div>
      )}

      {error && !data ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : isLoading && !data ? (
        <RoutesSkeleton list />
      ) : options.length === 0 ? (
        <Card className="p-5">
          <Text variant="body" tone="secondary">
            No routes found for this journey right now.
          </Text>
        </Card>
      ) : (
        <div className="flex flex-col gap-3" aria-busy={isLoading || undefined}>
          {axis && (
            <div className="px-1">
              <AxisLabels axis={axis} />
            </div>
          )}
          {(startError || usualError) && (
            <Text variant="footnote" tone="attention" role="alert" className="px-1">
              {startError ?? usualError}
            </Text>
          )}
          {options.map((o) => (
            <OptionCard
              key={o.id}
              option={o}
              axis={axis}
              canStart={!activeTrip}
              starting={pending === o.id}
              savingUsual={savingUsual === o.id}
              onStart={async () => {
                if (commuteId && (await start(commuteId, o))) nav.go('today')
              }}
              onMakeUsual={() => makeUsual(o.id)}
            />
          ))}
          <Text variant="caption" tone="tertiary" className="px-1 text-pretty">
            Bars show the likely arrival range (10th–90th percentile) on a shared timeline. Narrower is more reliable.
          </Text>
        </div>
      )}
    </div>
  )
}

function RoutesSkeleton({ list }: { list?: boolean }) {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading routes">
      {!list && <Skeleton className="h-11 w-full rounded-full" />}
      {[0, 1, 2].map((i) => (
        <Card key={i} className="flex flex-col gap-3 p-5">
          <Skeleton className="h-6 w-24 rounded-full" />
          <Skeleton className="h-7 w-48" />
          <Skeleton className="h-9 w-32" />
          <Skeleton className="h-2.5 w-full rounded-full" />
        </Card>
      ))}
    </div>
  )
}
