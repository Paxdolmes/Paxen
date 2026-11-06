import { useMemo, useState } from 'react'
import { View } from 'react-native'
import { router, useLocalSearchParams } from 'expo-router'
import { mutate } from 'swr'
import { fmtMin, PREFERENCE_LABELS, PREFERENCES } from '@/shared/format'
import type { Preference } from '@/shared/types'
import { api } from '@/lib/api'
import { useActiveTrip, useCompare, useDashboard } from '@/lib/hooks'
import { useStartTrip } from '@/lib/trip-actions'
import { OptionCard } from '@/components/option-card'
import { Screen } from '@/components/screen'
import { Text } from '@/components/text'
import { AxisLabels, buildAxis, CommuteStatusPill } from '@/components/transit'
import { Card, ErrorState, ErrorText, Segmented, Skeleton } from '@/components/ui'

export default function RoutesScreen() {
  const params = useLocalSearchParams<{ commute?: string; pref?: Preference }>()
  const { data: dashboard } = useDashboard()
  const commutes = dashboard?.commutes ?? []
  const commuteId =
    (commutes.some((c) => c.commute.id === params.commute) && params.commute) || dashboard?.active_commute_id || commutes[0]?.commute.id || null
  const base = commutes.find((c) => c.commute.id === commuteId)
  const pref: Preference = (params.pref && PREFERENCES.includes(params.pref) ? params.pref : undefined) ?? base?.commute.preference ?? 'balanced'

  const { data, error, isLoading, mutate: refetch } = useCompare(commuteId, pref)
  const { start, pending, error: startError } = useStartTrip()
  const activeTrip = useActiveTrip()
  const [savingUsual, setSavingUsual] = useState<string | null>(null)
  const [usualError, setUsualError] = useState<string | null>(null)

  const options = useMemo(() => data?.options ?? [], [data])
  const axis = useMemo(() => buildAxis(options.filter((o) => o.feasible).map((o) => o.arrive_range)), [options])

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

  return (
    <Screen title="Compare routes" gap={20} onRefresh={() => refetch()}>
      {!dashboard ? (
        <RoutesSkeleton />
      ) : (
        <>
          {commutes.length > 1 && (
            <Segmented
              label="Commute"
              value={commuteId ?? ''}
              options={commutes.map((c) => ({ value: c.commute.id, label: c.commute.name }))}
              onChange={(id) => router.setParams({ commute: id, pref: '' })}
            />
          )}
          <Segmented
            label="Route preference"
            scroll
            value={pref}
            options={PREFERENCES.map((p) => ({ value: p, label: PREFERENCE_LABELS[p] }))}
            onChange={(p) => router.setParams({ commute: commuteId ?? '', pref: p })}
          />

          {data && (
            <View style={{ gap: 4, paddingHorizontal: 4 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <CommuteStatusPill status={data.status} />
                <Text variant="footnote" tone="secondary" tabular style={{ flexShrink: 1 }}>
                  {data.commute.origin.name} → {data.commute.dest.name}
                </Text>
              </View>
              <Text variant="headline">{data.headline}</Text>
              {data.chosen_stops_honoured === false && (
                <Text variant="footnote" tone="watch">
                  Nothing is running from your chosen stations right now, so these routes use other stations.
                </Text>
              )}
              <Text variant="footnote" tone="secondary" tabular>
                {data.baseline.p50 != null ? `Normal: ${fmtMin(data.baseline.p50)} · ${data.baseline.label}` : 'Learning your routine'}
              </Text>
            </View>
          )}

          {error && !data ? (
            <ErrorState error={error} onRetry={() => refetch()} />
          ) : isLoading && !data ? (
            <RoutesSkeleton list />
          ) : options.length === 0 ? (
            <Card style={{ padding: 20 }}>
              <Text variant="body" tone="secondary">
                No routes found for this journey right now.
              </Text>
            </Card>
          ) : (
            <View style={{ gap: 12 }}>
              {axis && (
                <View style={{ paddingHorizontal: 4 }}>
                  <AxisLabels axis={axis} />
                </View>
              )}
              <ErrorText>{startError ?? usualError}</ErrorText>
              {options.map((o) => (
                <OptionCard
                  key={o.id}
                  option={o}
                  axis={axis}
                  canStart={!activeTrip}
                  starting={pending === o.id}
                  savingUsual={savingUsual === o.id}
                  onStart={async () => {
                    if (commuteId && (await start(commuteId, o))) router.push('/live')
                  }}
                  onMakeUsual={() => makeUsual(o.id)}
                />
              ))}
              <Text variant="caption" tone="tertiary" style={{ paddingHorizontal: 4 }}>
                Bars show the likely arrival range (10th–90th percentile) on a shared timeline. Narrower is more reliable.
              </Text>
            </View>
          )}
        </>
      )}
    </Screen>
  )
}

function RoutesSkeleton({ list }: { list?: boolean }) {
  return (
    <View style={{ gap: 12 }} accessibilityLabel="Loading routes">
      {!list && <Skeleton style={{ height: 44, borderRadius: 22 }} />}
      {[0, 1, 2].map((i) => (
        <Card key={i} style={{ padding: 20, gap: 12 }}>
          <Skeleton style={{ height: 24, width: 96, borderRadius: 12 }} />
          <Skeleton style={{ height: 28, width: 192 }} />
          <Skeleton style={{ height: 36, width: 128 }} />
          <Skeleton style={{ height: 10, borderRadius: 5 }} />
        </Card>
      ))}
    </View>
  )
}
