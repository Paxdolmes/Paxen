'use client'

import dynamic from 'next/dynamic'
import { useEffect, useState } from 'react'
import { CircleCheck, Crosshair, Footprints, LocateFixed, MapPin, X } from 'lucide-react'
import { mutate } from 'swr'
import { api } from '@/lib/api'
import { fmtMin, fmtTime } from '@/lib/format'
import { activeTripStore, type ActiveTrip, useLiveTrip } from '@/lib/hooks'
import type { LiveTrip } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '../primitives/button'
import { Card, Skeleton } from '../primitives/card'
import { Text } from '../primitives/text'
import { ConfidenceBadge } from '../transit/confidence-badge'
import { LineChip } from '../transit/line-chip'
import { useGeolocation } from './use-geolocation'

const TripMap = dynamic(() => import('./trip-map'), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full rounded-none" />,
})

function phaseText(t: LiveTrip): string {
  const leg = t.legs[t.current_leg ?? 0]
  if (!leg) return ''
  if (t.phase === 'walking') return `Walk to ${leg.to}`
  if (t.phase === 'waiting') return `Waiting for the ${leg.line_name ?? 'next service'} at ${leg.from}`
  return `On the ${leg.line_name ?? 'service'} to ${leg.to}`
}

function Steps({ trip }: { trip: LiveTrip }) {
  const current = trip.status === 'active' ? (trip.current_leg ?? 0) : trip.legs.length
  return (
    <ol className="flex flex-col" aria-label="Journey steps">
      {trip.legs.map((l, i) => {
        const state = i < current ? 'done' : i === current ? 'now' : 'next'
        return (
          <li key={i} className="flex gap-3">
            <span className="flex w-6 flex-col items-center" aria-hidden>
              <span
                className={cn(
                  'mt-1.5 size-3 shrink-0 rounded-full border-2',
                  state === 'done' && 'border-px-text-tertiary bg-px-text-tertiary',
                  state === 'now' && 'border-px-brand bg-px-brand ring-4 ring-px-brand-soft',
                  state === 'next' && 'border-px-border-strong bg-px-surface',
                )}
              />
              {i < trip.legs.length - 1 && <span className="w-0.5 flex-1 bg-px-border" />}
            </span>
            <div className={cn('flex flex-1 flex-col gap-1 pb-4', state === 'done' && 'opacity-50')}>
              {l.mode === 'walking' ? (
                <Text variant="callout" style={{ fontWeight: state === 'now' ? 700 : 500 }}>
                  <Footprints className="mr-1.5 inline size-4 align-[-2px]" aria-hidden />
                  Walk {fmtMin(l.ride_min)} to {l.to}
                </Text>
              ) : (
                <>
                  <span className="flex flex-wrap items-center gap-2">
                    <LineChip mode={l.mode} name={l.line_name ?? l.mode} />
                    <Text variant="footnote" tone="secondary">
                      {l.direction ? `towards ${l.direction}` : ''}
                    </Text>
                  </span>
                  <Text variant="callout" style={{ fontWeight: state === 'now' ? 700 : 500 }}>
                    {l.from} → {l.to} · {fmtMin(l.ride_min)}
                  </Text>
                </>
              )}
              {state === 'now' && <span className="sr-only">(current step)</span>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function Ended({ trip, onDone }: { trip: LiveTrip; onDone: () => void }) {
  const arrived = trip.status === 'arrived'
  const vs = trip.vs_forecast_min
  return (
    <Card className="flex flex-col items-center gap-3 p-6 text-center">
      <span className="flex size-14 items-center justify-center rounded-full bg-px-success-soft text-px-success">
        <CircleCheck className="size-8" aria-hidden />
      </span>
      <Text variant="title1" as="h2">
        {arrived ? `You've arrived` : 'Trip closed'}
      </Text>
      <Text variant="callout" tone="secondary" className="text-pretty">
        {arrived && trip.duration_min != null
          ? `${fmtMin(trip.duration_min)} door to door${
              vs == null ? '' : Math.abs(vs) < 1 ? ', right on forecast.' : vs < 0 ? `, ${fmtMin(-vs)} quicker than forecast.` : `, ${fmtMin(vs)} longer than forecast.`
            } This trip now helps Paxen learn your normal.`
          : trip.status === 'too_fast'
            ? `That was quicker than the route allows, so this trip won't be used to learn your normal.`
            : `We didn't see you arrive, so this trip won't be used to learn your normal.`}
      </Text>
      <Button block onClick={onDone}>
        Done
      </Button>
    </Card>
  )
}

export function LiveTripScreen({ active, onClose }: { active: ActiveTrip; onClose: () => void }) {
  const geo = useGeolocation()
  const { data: trip, error } = useLiveTrip(active.id, geo.pos)
  const [follow, setFollow] = useState(true)
  const [busy, setBusy] = useState<'arrive' | 'cancel' | null>(null)
  const position: [number, number] | null = geo.pos ? [geo.pos.lat, geo.pos.lon] : null

  const finish = async () => {
    activeTripStore.set(null)
    await mutate((key) => Array.isArray(key) && ['dashboard', 'insights', 'trips'].includes(key[0] as string))
    onClose()
  }
  const arriveNow = async () => {
    setBusy('arrive')
    try {
      await api.arrive(active.id)
      await mutate((key) => Array.isArray(key) && key[0] === 'live')
    } finally {
      setBusy(null)
    }
  }
  const cancel = async () => {
    setBusy('cancel')
    try {
      await api.cancelTrip(active.id)
    } catch {
      /* already gone */
    }
    setBusy(null)
    finish()
  }

  useEffect(() => {
    document.title = trip?.eta ? `Arrive ${fmtTime(trip.eta)} · Paxen` : 'Live trip · Paxen'
  }, [trip?.eta])

  const ended = trip && trip.status !== 'active'

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-[430px] flex-col bg-px-canvas">
      <header className="flex items-center gap-3 px-4 pb-2 pt-safe">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close live trip"
          className="-ml-1 mt-2 flex size-11 items-center justify-center rounded-full text-px-text hover:bg-px-surface-sunken"
        >
          <X className="size-5" aria-hidden />
        </button>
        <div className="mt-2 flex min-w-0 flex-col">
          <Text variant="caption" tone="brand" style={{ fontWeight: 700 }}>
            LIVE TRIP
          </Text>
          <Text variant="headline" className="truncate">
            {trip?.summary ?? active.summary}
          </Text>
        </div>
      </header>

      <div className="relative h-[42dvh] min-h-64 w-full overflow-hidden border-y border-px-border">
        {trip ? (
          <TripMap trip={trip} position={position} follow={follow && !!position} />
        ) : (
          <Skeleton className="h-full w-full rounded-none" />
        )}
        {trip && !trip.legs.some((l) => l.path?.length) && (
          <div className="absolute inset-0 flex items-center justify-center bg-px-surface-sunken">
            <Text variant="footnote" tone="secondary">
              Map not available for this trip
            </Text>
          </div>
        )}
        {position && (
          <button
            type="button"
            onClick={() => setFollow((f) => !f)}
            aria-pressed={follow}
            aria-label={follow ? 'Stop following my position' : 'Follow my position'}
            className="absolute bottom-3 right-3 z-[500] flex size-11 items-center justify-center rounded-full bg-px-surface shadow-md"
          >
            {follow ? <LocateFixed className="size-5 text-px-accent" aria-hidden /> : <Crosshair className="size-5" aria-hidden />}
          </button>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-4 px-5 pb-10 pt-4" aria-live="polite">
        {error && !trip ? (
          <Text variant="callout" tone="attention">
            Couldn&apos;t load your trip. Check your connection; we&apos;ll keep trying.
          </Text>
        ) : !trip ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-16 w-2/3" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : ended ? (
          <Ended trip={trip} onDone={finish} />
        ) : (
          <>
            <div className="flex items-end justify-between gap-4">
              <div className="flex flex-col">
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
              </div>
              <div className="flex flex-col items-end gap-1">
                <Text variant="title1" tabular>
                  {trip.remaining_min ? `${fmtMin(trip.remaining_min.p50)} left` : ''}
                </Text>
                {trip.confidence && <ConfidenceBadge confidence={trip.confidence} />}
              </div>
            </div>

            <Card className="flex flex-col gap-2 p-4">
              <Text variant="headline">{phaseText(trip)}</Text>
              {trip.next_departure && (
                <Text variant="callout" tone="secondary" className="text-pretty">
                  Next {trip.next_departure.line_name} from {trip.next_departure.stop}{' '}
                  {trip.next_departure.departures_min.length
                    ? `in ${fmtMin(trip.next_departure.departures_min[0])}${
                        trip.next_departure.departures_min.length > 1
                          ? `, then ${trip.next_departure.departures_min.slice(1, 3).map((m) => Math.round(m)).join(', ')} min`
                          : ''
                      }`
                    : `about every ${fmtMin(Math.max(1, trip.next_departure.wait_min * 2))}`}
                  {trip.next_departure.live ? ' · live' : ' · scheduled'}
                </Text>
              )}
              {trip.disruptions?.map((d) => (
                <Text key={d.line_id} variant="footnote" tone="attention" className="text-pretty">
                  {d.line_name}: {d.description}
                </Text>
              ))}
            </Card>

            {geo.state !== 'watching' ? (
              <div className="flex items-start gap-3 rounded-px-md border border-px-border bg-px-surface p-4">
                <MapPin className="mt-0.5 size-5 shrink-0 text-px-text-secondary" aria-hidden />
                <div className="flex flex-1 flex-col gap-2">
                  <Text variant="footnote" tone="secondary" className="text-pretty">
                    {geo.state === 'denied'
                      ? 'Location is off for Paxen, so progress follows the clock. You can allow it in your browser settings.'
                      : geo.state === 'unavailable'
                        ? 'Your location isn’t available right now, so progress follows the clock.'
                        : 'Progress is following the clock. Share your location while this screen is open for live progress and automatic arrival. It’s never stored.'}
                  </Text>
                  {(geo.state === 'idle' || geo.state === 'prompt') && (
                    <Button size="sm" variant="secondary" onClick={geo.start} loading={geo.state === 'prompt'}>
                      Use my location
                    </Button>
                  )}
                </div>
              </div>
            ) : (
              <Text variant="footnote" tone="secondary">
                Using your location while this screen is open. Your trip ends by itself when you arrive.
              </Text>
            )}

            <Steps trip={trip} />

            <div className="mt-auto flex flex-col gap-2">
              <Button variant="secondary" block onClick={arriveNow} loading={busy === 'arrive'}>
                I&apos;ve arrived
              </Button>
              <Button variant="ghost" block onClick={cancel} loading={busy === 'cancel'}>
                Cancel trip
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
