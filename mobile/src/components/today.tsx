import { useState, useSyncExternalStore } from 'react'
import { Linking, Platform, Pressable, View } from 'react-native'
import { router } from 'expo-router'
import { ArrowRight, CalendarClock, MapPinned, ChevronRight, CloudRain, Map as MapIcon, Navigation, Play, Sparkles, Sun, Wind } from 'lucide-react-native'
import { fareLabel, fmtMin, fmtTime } from '@/shared/format'
import { radii } from '@/shared/paxen-tokens'
import { crowdingWords, usuallyRange } from '@/shared/plain'
import type { CommuteEvaluation, Conditions, LineStatus, UpcomingDisruption } from '@/shared/types'
import { enableAutoTrips } from '@/lib/autotrips'
import { type ActiveTrip, revalidateAll, useActiveTrip, useLiveTrip } from '@/lib/hooks'
import { persisted } from '@/lib/storage'
import { usePalette } from '@/lib/theme'
import { useStartTrip } from '@/lib/trip-actions'
import { Text } from './text'
import {
  commuteStatusMeta,
  CommuteStatusPill,
  ConfidenceBadge,
  CrowdingChip,
  DisruptionNote,
  LegStrip,
  LineChip,
  LineStatusText,
  SeverityDot,
} from './transit'
import { Button, Card, Chip, Disclosure, Divider, ErrorText } from './ui'

const openLive = () => router.push('/live')

function TimeBlock({ label, time }: { label: string; time: string }) {
  return (
    <View style={{ flex: 1 }}>
      <Text variant="subhead" tone="secondary" style={{ fontWeight: '600' }}>
        {label}
      </Text>
      <Text variant="display" tabular>
        {time}
      </Text>
    </View>
  )
}

export function CommuteHero({ evaluation, onCompare }: { evaluation: CommuteEvaluation; onCompare: () => void }) {
  const p = usePalette()
  const { commute, status, headline, detail, recommended: rec, usual, baseline, delta_min } = evaluation
  const meta = commuteStatusMeta(p)[status]
  const StatusIcon = meta.icon
  const activeTrip = useActiveTrip()
  const { start, pending, error } = useStartTrip()
  const tripHere = activeTrip?.commute_id === commute.id ? activeTrip : null

  const switched = rec && usual && rec.id !== usual.id
  const gain = evaluation.gain_min ?? (rec?.vs_usual_min != null ? -rec.vs_usual_min : null)
  const slowerBy = delta_min != null && Math.round(delta_min) > 0 ? Math.round(delta_min) : null
  const range = rec ? usuallyRange(rec.duration.p10, rec.duration.p90) : null

  return (
    <Card style={{ overflow: 'hidden' }}>
      <View style={{ backgroundColor: meta.bg, paddingHorizontal: 20, paddingTop: 16, paddingBottom: 20, gap: 8 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 1 }}>
            <StatusIcon size={16} color={meta.fg} />
            <Text variant="footnote" color={meta.fg} style={{ fontWeight: '700' }} numberOfLines={1}>
              {meta.label}
            </Text>
          </View>
          <Text variant="footnote" color={meta.fg} tabular style={{ opacity: 0.9 }}>
            {commute.name} · {commute.window_start}–{commute.window_end}
          </Text>
        </View>
        <Text variant="title1" color={meta.fg} accessibilityRole="header">
          {headline}
        </Text>
        {detail ? (
          <Text variant="subhead" color={meta.fg}>
            {detail}
          </Text>
        ) : null}
        {evaluation.chosen_stops_honoured === false && (
          <Text variant="footnote" color={meta.fg}>
            Nothing is running from your chosen stations right now, so these routes use other stations.
          </Text>
        )}
      </View>

      <View style={{ padding: 20, gap: 20 }}>
        {tripHere ? (
          <TripInProgress trip={tripHere} />
        ) : rec ? (
          <>
            <View style={{ gap: 8 }}>
              <View style={{ flexDirection: 'row', gap: 16 }}>
                <TimeBlock label="Leave by" time={fmtTime(rec.depart_at)} />
                <TimeBlock label="Arrive about" time={fmtTime(rec.arrive_at)} />
              </View>
              <Text variant="subhead" tone="secondary" tabular>
                {fmtMin(rec.duration.p50)} door to door{range ? ` · ${range}` : ''}
              </Text>
              {slowerBy != null && (
                <Chip tone="attention" size="md">
                  {slowerBy} min slower than usual
                </Chip>
              )}
            </View>

            {switched && (
              <View style={{ flexDirection: 'row', gap: 8, borderRadius: radii.md, backgroundColor: p.brandSoft, padding: 16 }}>
                <Sparkles size={16} color={p.onBrandSoft} style={{ marginTop: 3 }} />
                <Text variant="callout" color={p.onBrandSoft} style={{ fontWeight: '600', flex: 1 }}>
                  Better today: take {rec.summary}
                  {gain != null && Math.round(gain) > 0 ? ` — ${Math.round(gain)} min sooner` : ''}
                </Text>
              </View>
            )}

            <View style={{ gap: 8 }}>
              <Button
                block
                onPress={async () => {
                  if (await start(commute.id, rec)) openLive()
                }}
                loading={pending === rec.id}
                disabled={!rec.feasible}
                icon={(c) => <Play size={16} color={c} fill={c} />}
              >
                I&apos;m leaving now
              </Button>
              <Button variant="secondary" block onPress={onCompare} icon={(c) => <ArrowRight size={16} color={c} />}>
                See other routes
              </Button>
              <ErrorText>{error}</ErrorText>
            </View>

            <View style={{ borderTopWidth: 1, borderTopColor: p.border, paddingTop: 4 }}>
              <Disclosure label="Route details" openLabel="Hide route details">
                <View style={{ gap: 8 }}>
                  <Text variant="subhead" tone="secondary" style={{ fontWeight: '600' }}>
                    {switched ? 'Recommended route' : 'Your route'}
                  </Text>
                  <LegStrip legs={rec.legs} />
                </View>

                {switched && usual && (
                  <View style={{ gap: 8, borderRadius: radii.md, borderWidth: 1, borderStyle: 'dashed', borderColor: p.borderStrong, padding: 12 }}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                      <Text variant="footnote" tone="secondary" style={{ flex: 1 }}>
                        Your usual: <Text variant="footnote" tone="secondary" style={{ textDecorationLine: 'line-through' }}>{usual.summary}</Text>
                      </Text>
                      <Text variant="footnote" tone="secondary" tabular>
                        {usual.feasible ? fmtMin(usual.duration.p50) : 'Not running'}
                      </Text>
                    </View>
                    <LegStrip legs={usual.legs} showWait={false} muted />
                    {usual.disruptions.map((d) => (
                      <DisruptionNote key={d.line_id} disruption={d} withReason={false} />
                    ))}
                  </View>
                )}

                {rec.disruptions.length > 0 && (
                  <View style={{ gap: 8 }}>
                    {rec.disruptions.map((d) => (
                      <DisruptionNote key={d.line_id} disruption={d} />
                    ))}
                  </View>
                )}

                <View style={{ gap: 6 }}>
                  <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
                    <ConfidenceBadge confidence={rec.confidence} />
                    <CrowdingChip crowding={rec.crowding} />
                  </View>
                  {rec.crowding.level !== 'n/a' && (
                    <Text variant="footnote" tone="secondary">
                      {crowdingWords(rec.crowding.basis)}
                    </Text>
                  )}
                </View>

                <Text variant="footnote" tone="secondary" tabular>
                  {baseline.p50 != null ? (
                    <>
                      <Text variant="footnote" style={{ fontWeight: '600' }}>
                        Usually {fmtMin(baseline.p50)}
                      </Text>
                      {` · ${baseline.label}`}
                    </>
                  ) : (
                    `Still learning your usual trip · ${baseline.label}`
                  )}
                  {rec.fare ? ` · Fare ${fareLabel(rec.fare)}` : ''}
                </Text>
              </Disclosure>
            </View>
          </>
        ) : (
          <View style={{ gap: 12 }}>
            <Text variant="body" tone="secondary">
              No route is available for this journey right now.
            </Text>
            <Button variant="secondary" block onPress={onCompare}>
              See other routes
            </Button>
          </View>
        )}
      </View>
    </Card>
  )
}

/** Compact live summary on Today; the full live view (map, steps) opens from here. */
export function TripInProgress({ trip }: { trip: ActiveTrip }) {
  const p = usePalette()
  const { data: live } = useLiveTrip(trip.id, null)
  const ended = live && live.status !== 'active'
  const fallbackEta = new Date(new Date(trip.started_at).getTime() + trip.forecast_p50 * 60_000).toISOString()
  return (
    <View style={{ gap: 16 }} accessibilityLiveRegion="polite">
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Navigation size={16} color={p.brand} />
        <Text variant="footnote" tone="brand" style={{ fontWeight: '700', flex: 1 }}>
          {ended ? 'Trip finished' : 'On your way'} · {trip.summary}
        </Text>
      </View>
      {!ended && (
        <View style={{ flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16 }}>
          <View>
            <Text variant="caption" tone="secondary">
              Arrive
            </Text>
            <Text variant="display" tabular>
              ~{fmtTime(live?.eta ?? fallbackEta)}
            </Text>
          </View>
          <View style={{ alignItems: 'flex-end', flexShrink: 1 }}>
            <Text variant="title2" tabular>
              {live?.remaining_min ? `${fmtMin(live.remaining_min.p50)} left` : ''}
            </Text>
            {live?.next_departure?.departures_min?.length ? (
              <Text variant="footnote" tone="secondary" style={{ textAlign: 'right' }}>
                Next {live.next_departure.line_name} in {fmtMin(live.next_departure.departures_min[0])}
              </Text>
            ) : null}
          </View>
        </View>
      )}
      <Button block onPress={openLive} icon={(c) => <MapIcon size={16} color={c} />}>
        {ended ? 'See trip summary' : 'Open live map'}
      </Button>
    </View>
  )
}

/** Rain at departure and London air quality vs usual. Renders nothing when neither is known. */
export function ConditionsStrip({ conditions }: { conditions: Conditions | null | undefined }) {
  const p = usePalette()
  const w = conditions?.weather
  const aq = conditions?.air_quality
  if (!w && !aq) return null
  const aqBad = (aq?.level ?? 0) >= 2 || aq?.worse_than_usual
  return (
    <Card style={{ padding: 16, gap: 12 }}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', columnGap: 24, rowGap: 12 }}>
        {w && (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            {w.wet ? <CloudRain size={20} color={p.watch} /> : <Sun size={20} color={p.textSecondary} />}
            <View>
              <Text variant="callout" tone={w.wet ? 'watch' : 'primary'} style={{ fontWeight: '600' }}>
                {w.summary} at {w.time}
              </Text>
              <Text variant="caption" tone="secondary" tabular>
                {[w.temp_c != null ? `${Math.round(w.temp_c)}°C` : null, w.rain_prob != null ? `${w.rain_prob}% chance of rain` : null].filter(Boolean).join(' · ')}
              </Text>
            </View>
          </View>
        )}
        {aq && (
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Wind size={20} color={aqBad ? p.attention : p.textSecondary} />
            <View>
              <Text variant="callout" tone={aqBad ? 'attention' : 'primary'} style={{ fontWeight: '600' }}>
                Air quality: {aq.band}
              </Text>
              <Text variant="caption" tone="secondary">
                {aq.usual_band ? `Usually ${aq.usual_band}` : `Learning what's usual (${aq.history_days}/7 days)`}
                {aq.tomorrow_band ? ` · Tomorrow ${aq.tomorrow_band}` : ''}
              </Text>
            </View>
          </View>
        )}
      </View>
      {conditions?.walking_note ? (
        <Text variant="footnote" tone="secondary">
          {conditions.walking_note}
        </Text>
      ) : null}
    </Card>
  )
}

/** Planned closures in the next week on lines the user's routes use. */
export function UpcomingCard({ items }: { items: UpcomingDisruption[] }) {
  const p = usePalette()
  if (!items.length) return null
  return (
    <Card>
      {items.map((d, i) => (
        <View key={`${d.line_id}-${d.from}`}>
          {i > 0 && <Divider />}
          <View style={{ gap: 6, paddingHorizontal: 16, paddingVertical: 12 }}>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
              <LineChip mode={d.mode || 'tube'} name={d.line_name} status={d.category} />
              <Text variant="footnote" tone="attention" style={{ fontWeight: '600', flexShrink: 1 }}>
                {d.description}
              </Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <CalendarClock size={14} color={p.text} />
              <Text variant="footnote" style={{ fontWeight: '600', flexShrink: 1 }}>
                From {d.starts_local}
                {d.commutes.length ? ` · affects ${d.commutes.join(' and ')}` : ''}
              </Text>
            </View>
            {d.reason ? (
              <Text variant="caption" tone="secondary" numberOfLines={3}>
                {d.reason}
              </Text>
            ) : null}
          </View>
        </View>
      ))}
    </Card>
  )
}

export function OtherCommuteCard({ evaluation, onOpen }: { evaluation: CommuteEvaluation; onOpen: () => void }) {
  const p = usePalette()
  const { commute, status, recommended } = evaluation
  return (
    <Card>
      <Pressable accessibilityRole="button" onPress={onOpen} style={({ pressed }) => ({ flexDirection: 'row', alignItems: 'center', gap: 16, padding: 20, opacity: pressed ? 0.7 : 1 })}>
        <View style={{ flex: 1, gap: 4 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Text variant="headline">{commute.name}</Text>
            <CommuteStatusPill status={status} />
          </View>
          <Text variant="footnote" tone="secondary" tabular numberOfLines={1}>
            {commute.window_start}–{commute.window_end} · {commute.origin.name} → {commute.dest.name}
          </Text>
        </View>
        {recommended && (
          <View style={{ alignItems: 'flex-end' }}>
            <Text variant="title2" tabular>
              {fmtMin(recommended.duration.p50)}
            </Text>
            <Text variant="caption" tone="secondary">
              expected
            </Text>
          </View>
        )}
        <ChevronRight size={20} color={p.textTertiary} />
      </Pressable>
    </Card>
  )
}

export function LinesOnRoutes({ lines }: { lines: LineStatus[] }) {
  if (!lines.length) return null
  return (
    <Card>
      {lines.map((l, i) => (
        <View key={l.line_id}>
          {i > 0 && <Divider />}
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingHorizontal: 20, paddingVertical: 14 }}>
            <LineChip mode={l.mode} name={l.line_name} />
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1 }}>
              <SeverityDot category={l.category} />
              <LineStatusText category={l.category} description={l.description} />
            </View>
          </View>
        </View>
      ))}
    </Card>
  )
}

const nudgeStore = persisted('paxen.autoTripsNudge')

/** A one-time invitation to turn on automatic trips (iPhone only). */
export function AutoTripsNudge({ enabled }: { enabled: boolean }) {
  const p = usePalette()
  const dismissed = useSyncExternalStore(nudgeStore.subscribe, nudgeStore.get, nudgeStore.get)
  const [busy, setBusy] = useState(false)
  const [needsAlways, setNeedsAlways] = useState(false)
  if (enabled || Platform.OS === 'web' || dismissed === undefined || dismissed) return null
  const turnOn = async () => {
    setBusy(true)
    try {
      const res = await enableAutoTrips()
      if (res === 'on') {
        nudgeStore.set('done')
        await revalidateAll()
      } else setNeedsAlways(true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card style={{ padding: 16, gap: 12 }}>
      <View style={{ flexDirection: 'row', gap: 12 }}>
        <View style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: p.brandSoft, alignItems: 'center', justifyContent: 'center' }}>
          <MapPinned size={18} color={p.onBrandSoft} />
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <Text variant="headline">Let Paxen log your commutes</Text>
          <Text variant="footnote" tone="secondary">
            It notices when you leave and reach Home and Work, so it learns your normal without you pressing start. Only the times
            are sent, never where you are, and trips with a stop on the way are left out.
          </Text>
        </View>
      </View>
      {needsAlways ? (
        <View style={{ gap: 8 }}>
          <Text variant="footnote" tone="secondary">
            Set Location to Always for Paxen in Settings, then turn it on in You.
          </Text>
          <Button variant="secondary" size="md" onPress={() => Linking.openSettings()}>
            Open Settings
          </Button>
        </View>
      ) : (
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <Button size="md" onPress={turnOn} loading={busy}>
            Turn on
          </Button>
          <Button variant="ghost" size="md" onPress={() => nudgeStore.set('dismissed')}>
            Not now
          </Button>
        </View>
      )}
    </Card>
  )
}
