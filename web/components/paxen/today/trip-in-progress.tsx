'use client'

import { Map as MapIcon, Navigation } from 'lucide-react'
import { fmtMin, fmtTime } from '@/lib/format'
import type { ActiveTrip } from '@/lib/hooks'
import { useLiveTrip } from '@/lib/hooks'
import { Button } from '../primitives/button'
import { Text } from '../primitives/text'

/** Compact live summary on Today; the full live view (map, steps) opens from here. */
export function TripInProgress({ trip, onOpen }: { trip: ActiveTrip; onOpen: () => void }) {
  const { data: live } = useLiveTrip(trip.id, null)
  const ended = live && live.status !== 'active'
  return (
    <div className="flex flex-col gap-4" aria-live="polite">
      <div className="flex items-center gap-2 text-px-brand">
        <Navigation className="size-4" aria-hidden />
        <Text variant="footnote" tone="brand" style={{ fontWeight: 700 }}>
          {ended ? 'Trip finished' : 'On your way'} · {trip.summary}
        </Text>
      </div>
      {!ended && (
        <div className="flex items-end justify-between gap-4">
          <div className="flex flex-col">
            <Text variant="caption" tone="secondary">
              Arrive
            </Text>
            <Text variant="display" tabular>
              ~{live?.eta ? fmtTime(live.eta) : fmtTime(new Date(new Date(trip.started_at).getTime() + trip.forecast_p50 * 60_000).toISOString())}
            </Text>
          </div>
          <div className="flex flex-col items-end">
            <Text variant="title2" tabular>
              {live?.remaining_min ? `${fmtMin(live.remaining_min.p50)} left` : ''}
            </Text>
            {live?.next_departure?.departures_min?.length ? (
              <Text variant="footnote" tone="secondary">
                Next {live.next_departure.line_name} in {fmtMin(live.next_departure.departures_min[0])}
              </Text>
            ) : null}
          </div>
        </div>
      )}
      <Button block onClick={onOpen} icon={<MapIcon className="size-4" aria-hidden />}>
        {ended ? 'See trip summary' : 'Open live map'}
      </Button>
    </div>
  )
}
