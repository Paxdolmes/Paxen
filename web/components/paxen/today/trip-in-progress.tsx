'use client'

import { useEffect, useState } from 'react'
import { CircleCheck, Navigation } from 'lucide-react'
import { fmtMin, fmtTime } from '@/lib/format'
import type { ActiveTrip } from '@/lib/hooks'
import { activeTripStore } from '@/lib/hooks'
import { Button } from '../primitives/button'
import { Text } from '../primitives/text'
import { arriveTrip } from '../use-trip-actions'

function useNow(ms: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

export function TripInProgress({ trip }: { trip: ActiveTrip }) {
  const now = useNow(15_000)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const started = new Date(trip.started_at).getTime()
  const elapsed = Math.max(0, (now - started) / 60_000)
  const expected = new Date(started + trip.forecast_p50 * 60_000).toISOString()
  const progress = Math.min(1, elapsed / Math.max(1, trip.forecast_p50))

  const onArrive = async () => {
    setPending(true)
    setError(null)
    try {
      await arriveTrip(trip.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not log your arrival.')
      setPending(false)
    }
  }

  return (
    <div className="flex flex-col gap-4" aria-live="polite">
      <div className="flex items-center gap-2 text-px-brand">
        <Navigation className="size-4" aria-hidden />
        <Text variant="footnote" tone="brand" style={{ fontWeight: 700 }}>
          On your way · {trip.summary}
        </Text>
      </div>
      <div className="flex items-end justify-between gap-4">
        <div className="flex flex-col">
          <Text variant="caption" tone="secondary">
            Elapsed
          </Text>
          <Text variant="display" tabular>
            {fmtMin(elapsed)}
          </Text>
        </div>
        <div className="flex flex-col items-end">
          <Text variant="caption" tone="secondary">
            Expected arrival
          </Text>
          <Text variant="title2" tabular>
            ~{fmtTime(expected)}
          </Text>
        </div>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-px-surface-sunken" aria-hidden>
        <div className="h-full rounded-full bg-px-brand transition-[width] duration-700" style={{ width: `${progress * 100}%` }} />
      </div>
      <div className="flex flex-col gap-2">
        <Button block onClick={onArrive} loading={pending} icon={<CircleCheck className="size-5" aria-hidden />}>
          I&apos;ve arrived
        </Button>
        <Button variant="ghost" size="md" block onClick={() => activeTripStore.set(null)} disabled={pending}>
          Cancel trip
        </Button>
        {error && (
          <Text variant="footnote" tone="attention" role="alert">
            {error}
          </Text>
        )}
      </div>
      <Text variant="footnote" tone="tertiary" className="text-pretty">
        Logging arrivals teaches Paxen what your normal really is.
      </Text>
    </div>
  )
}
