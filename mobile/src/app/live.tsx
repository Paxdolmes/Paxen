import { useState } from 'react'
import { Pressable, ScrollView, View } from 'react-native'
import { router } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { CircleCheck, Crosshair, Footprints, LocateFixed, MapPin, X } from 'lucide-react-native'
import { mutate } from 'swr'
import { fmtMin, fmtTime } from '@/shared/format'
import { layout, radii } from '@/shared/paxen-tokens'
import type { LiveTrip } from '@/shared/types'
import { api } from '@/lib/api'
import { activeTripStore, useActiveTrip, useLiveTrip } from '@/lib/hooks'
import { useGeolocation } from '@/lib/location'
import { usePalette, useShadow } from '@/lib/theme'
import { refreshAfterTrip } from '@/lib/trip-actions'
import { Text } from '@/components/text'
import TripMap from '@/components/trip-map'
import { ConfidenceBadge, LineChip } from '@/components/transit'
import { Button, Card, Skeleton } from '@/components/ui'

function phaseText(t: LiveTrip): string {
  const leg = t.legs[t.current_leg ?? 0]
  if (!leg) return ''
  if (t.phase === 'walking') return `Walk to ${leg.to}`
  if (t.phase === 'waiting') return `Waiting for the ${leg.line_name ?? 'next service'} at ${leg.from}`
  return `On the ${leg.line_name ?? 'service'} to ${leg.to}`
}

function Steps({ trip }: { trip: LiveTrip }) {
  const p = usePalette()
  const current = trip.status === 'active' ? (trip.current_leg ?? 0) : trip.legs.length
  return (
    <View accessibilityLabel="Journey steps">
      {trip.legs.map((l, i) => {
        const state = i < current ? 'done' : i === current ? 'now' : 'next'
        return (
          <View key={i} style={{ flexDirection: 'row', gap: 12 }} accessibilityLabel={state === 'now' ? 'Current step' : undefined}>
            <View style={{ width: 24, alignItems: 'center' }}>
              <View
                style={{
                  marginTop: 6,
                  width: state === 'now' ? 14 : 12,
                  height: state === 'now' ? 14 : 12,
                  borderRadius: 7,
                  borderWidth: 2,
                  borderColor: state === 'done' ? p.textTertiary : state === 'now' ? p.brand : p.borderStrong,
                  backgroundColor: state === 'done' ? p.textTertiary : state === 'now' ? p.brand : p.surface,
                  ...(state === 'now' ? { shadowColor: p.brand, shadowOpacity: 0.35, shadowRadius: 4, shadowOffset: { width: 0, height: 0 } } : {}),
                }}
              />
              {i < trip.legs.length - 1 && <View style={{ width: 2, flex: 1, backgroundColor: p.border }} />}
            </View>
            <View style={{ flex: 1, gap: 4, paddingBottom: 16, opacity: state === 'done' ? 0.5 : 1 }}>
              {l.mode === 'walking' ? (
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                  <Footprints size={16} color={p.text} />
                  <Text variant="callout" style={{ fontWeight: state === 'now' ? '700' : '500', flex: 1 }}>
                    Walk {fmtMin(l.ride_min)} to {l.to}
                  </Text>
                </View>
              ) : (
                <>
                  <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
                    <LineChip mode={l.mode} name={l.line_name ?? l.mode} />
                    {l.direction ? (
                      <Text variant="footnote" tone="secondary">
                        towards {l.direction}
                      </Text>
                    ) : null}
                  </View>
                  <Text variant="callout" style={{ fontWeight: state === 'now' ? '700' : '500' }}>
                    {l.from} → {l.to} · {fmtMin(l.ride_min)}
                  </Text>
                </>
              )}
            </View>
          </View>
        )
      })}
    </View>
  )
}

function Ended({ trip, onDone }: { trip: LiveTrip; onDone: () => void }) {
  const p = usePalette()
  const arrived = trip.status === 'arrived'
  const vs = trip.vs_forecast_min
  return (
    <Card style={{ padding: 24, gap: 12, alignItems: 'center' }}>
      <View style={{ width: 56, height: 56, borderRadius: 28, backgroundColor: p.successSoft, alignItems: 'center', justifyContent: 'center' }}>
        <CircleCheck size={32} color={p.success} />
      </View>
      <Text variant="title1">{arrived ? `You've arrived` : 'Trip closed'}</Text>
      <Text variant="callout" tone="secondary" style={{ textAlign: 'center' }}>
        {arrived && trip.duration_min != null
          ? `${fmtMin(trip.duration_min)} door to door${
              vs == null ? '' : Math.abs(vs) < 1 ? ', right on forecast.' : vs < 0 ? `, ${fmtMin(-vs)} quicker than forecast.` : `, ${fmtMin(vs)} longer than forecast.`
            } This trip now helps Paxen learn your normal.`
          : trip.status === 'too_fast'
            ? `That was quicker than the route allows, so this trip won't be used to learn your normal.`
            : trip.status === 'too_slow'
              ? `That took much longer than any route would, so it looks like there was a stop on the way. It won't be used to learn your normal.`
            : `We didn't see you arrive, so this trip won't be used to learn your normal.`}
      </Text>
      <Button block onPress={onDone}>
        Done
      </Button>
    </Card>
  )
}

export default function LiveTripScreen() {
  const active = useActiveTrip()
  const p = usePalette()
  const insets = useSafeAreaInsets()
  const shadow = useShadow('raised')
  const geo = useGeolocation()
  const { data: trip, error } = useLiveTrip(active?.id ?? null, geo.pos)
  const [follow, setFollow] = useState(true)
  const [busy, setBusy] = useState<'arrive' | 'cancel' | null>(null)
  const position: [number, number] | null = geo.pos ? [geo.pos.lat, geo.pos.lon] : null

  const close = () => (router.canGoBack() ? router.back() : router.replace('/'))
  const finish = async () => {
    activeTripStore.set(null)
    await refreshAfterTrip()
    close()
  }
  const arriveNow = async () => {
    if (!active) return
    setBusy('arrive')
    try {
      await api.arrive(active.id)
      await mutate((key) => Array.isArray(key) && key[0] === 'live')
    } finally {
      setBusy(null)
    }
  }
  const cancel = async () => {
    if (!active) return
    setBusy('cancel')
    try {
      await api.cancelTrip(active.id)
    } catch {
      /* already gone */
    }
    setBusy(null)
    finish()
  }

  const ended = trip && trip.status !== 'active'
  const hasPath = !!trip?.legs.some((l) => l.path?.length)

  return (
    <View style={{ flex: 1, backgroundColor: p.canvas }}>
      <View style={{ paddingTop: insets.top, paddingHorizontal: 16, paddingBottom: 8, flexDirection: 'row', alignItems: 'center', gap: 12 }}>
        <Pressable accessibilityRole="button" accessibilityLabel="Close live trip" onPress={close} hitSlop={8} style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
          <X size={20} color={p.text} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text variant="caption" tone="brand" style={{ fontWeight: '700' }}>
            LIVE TRIP
          </Text>
          <Text variant="headline" numberOfLines={1}>
            {trip?.summary ?? active?.summary ?? 'No trip in progress'}
          </Text>
        </View>
      </View>

      {!active ? (
        <View style={{ padding: layout.gutter, gap: 12 }}>
          <Text variant="body" tone="secondary">
            There&apos;s no trip in progress. Start one from Today when you leave.
          </Text>
          <Button block onPress={close}>
            Back to Today
          </Button>
        </View>
      ) : (
        <>
          <View style={{ height: 320, borderTopWidth: 1, borderBottomWidth: 1, borderColor: p.border, overflow: 'hidden' }}>
            {trip ? (
              hasPath ? (
                <TripMap trip={trip} position={position} follow={follow && !!position} />
              ) : (
                <View style={{ flex: 1, backgroundColor: p.surfaceSunken, alignItems: 'center', justifyContent: 'center' }}>
                  <Text variant="footnote" tone="secondary">
                    Map not available for this trip
                  </Text>
                </View>
              )
            ) : (
              <Skeleton style={{ flex: 1, borderRadius: 0 }} />
            )}
            {position && hasPath && (
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ selected: follow }}
                accessibilityLabel={follow ? 'Stop following my position' : 'Follow my position'}
                onPress={() => setFollow((f) => !f)}
                style={[{ position: 'absolute', bottom: 12, right: 12, width: 44, height: 44, borderRadius: 22, backgroundColor: p.surface, alignItems: 'center', justifyContent: 'center' }, shadow]}
              >
                {follow ? <LocateFixed size={20} color={p.brand} /> : <Crosshair size={20} color={p.text} />}
              </Pressable>
            )}
          </View>

          <ScrollView contentContainerStyle={{ flexGrow: 1, gap: 16, paddingHorizontal: layout.gutter, paddingTop: 16, paddingBottom: insets.bottom + 24 }}>
            {error && !trip ? (
              <Text variant="callout" tone="attention">
                Couldn&apos;t load your trip. Check your connection; we&apos;ll keep trying.
              </Text>
            ) : !trip ? (
              <View style={{ gap: 12 }}>
                <Skeleton style={{ height: 64, width: '66%' }} />
                <Skeleton style={{ height: 96 }} />
              </View>
            ) : ended ? (
              <Ended trip={trip} onDone={finish} />
            ) : (
              <>
                <View style={{ flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16 }} accessibilityLiveRegion="polite">
                  <View>
                    <Text variant="caption" tone="secondary">
                      Arrive
                    </Text>
                    <Text variant="display" tabular>
                      ~{trip.eta ? fmtTime(trip.eta) : '–'}
                    </Text>
                    {trip.eta_range && (
                      <Text variant="footnote" tone="secondary" tabular>
                        Likely {fmtTime(trip.eta_range[0])}–{fmtTime(trip.eta_range[1])}
                      </Text>
                    )}
                  </View>
                  <View style={{ alignItems: 'flex-end', gap: 4 }}>
                    <Text variant="title1" tabular>
                      {trip.remaining_min ? `${fmtMin(trip.remaining_min.p50)} left` : ''}
                    </Text>
                    {trip.confidence && <ConfidenceBadge confidence={trip.confidence} />}
                  </View>
                </View>

                <Card style={{ padding: 16, gap: 8 }}>
                  <Text variant="headline">{phaseText(trip)}</Text>
                  {trip.next_departure && (
                    <Text variant="callout" tone="secondary">
                      Next {trip.next_departure.line_name} from {trip.next_departure.stop}{' '}
                      {trip.next_departure.departures_min.length
                        ? `in ${fmtMin(trip.next_departure.departures_min[0])}${
                            trip.next_departure.departures_min.length > 1
                              ? `, then ${trip.next_departure.departures_min
                                  .slice(1, 3)
                                  .map((m) => Math.round(m))
                                  .join(', ')} min`
                              : ''
                          }`
                        : `about every ${fmtMin(Math.max(1, trip.next_departure.wait_min * 2))}`}
                      {trip.next_departure.live ? ' · live' : ' · scheduled'}
                    </Text>
                  )}
                  {trip.disruptions?.map((d) => (
                    <Text key={d.line_id} variant="footnote" tone="attention">
                      {d.line_name}: {d.description}
                    </Text>
                  ))}
                </Card>

                {geo.state !== 'watching' ? (
                  <View style={{ flexDirection: 'row', gap: 12, borderRadius: radii.md, borderWidth: 1, borderColor: p.border, backgroundColor: p.surface, padding: 16 }}>
                    <MapPin size={20} color={p.textSecondary} style={{ marginTop: 2 }} />
                    <View style={{ flex: 1, gap: 8 }}>
                      <Text variant="footnote" tone="secondary">
                        {geo.state === 'denied'
                          ? 'Location is off for Paxen, so progress follows the clock. You can allow it in Settings.'
                          : geo.state === 'unavailable'
                            ? 'Your location isn’t available right now, so progress follows the clock.'
                            : 'Progress is following the clock. Share your location while this screen is open for live progress and automatic arrival. It’s never stored.'}
                      </Text>
                      {(geo.state === 'idle' || geo.state === 'prompt') && (
                        <Button size="sm" variant="secondary" onPress={geo.start} loading={geo.state === 'prompt'}>
                          Use my location
                        </Button>
                      )}
                    </View>
                  </View>
                ) : (
                  <Text variant="footnote" tone="secondary">
                    Using your location while this screen is open. Your trip ends by itself when you arrive.
                  </Text>
                )}

                <Steps trip={trip} />

                <View style={{ marginTop: 'auto', gap: 8 }}>
                  <Button variant="secondary" block onPress={arriveNow} loading={busy === 'arrive'}>
                    I&apos;ve arrived
                  </Button>
                  <Button variant="ghost" block onPress={cancel} loading={busy === 'cancel'}>
                    Cancel trip
                  </Button>
                </View>
              </>
            )}
          </ScrollView>
        </>
      )}
    </View>
  )
}
