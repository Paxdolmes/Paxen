'use client'

import { Bus, Check, Footprints, TrainFront } from 'lucide-react'
import { useNearbyStops } from '@/lib/hooks'
import type { ChosenStop, NearbyStop } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Skeleton } from './primitives/card'
import { Text } from './primitives/text'

const MAX_STOPS = 6

export function toChosen(s: NearbyStop): ChosenStop {
  const { stop_id, name, kind, lat, lon, walk_min, hub, modes, lines, indicator } = s
  return { stop_id, name, kind, lat, lon, walk_min, hub, modes, lines, indicator }
}

function StopRow({ stop, selected, onToggle, disabled }: {
  stop: NearbyStop
  selected: boolean
  onToggle: () => void
  disabled: boolean
}) {
  const Icon = stop.kind === 'bus' ? Bus : TrainFront
  const title = stop.name
  // Bus stops share names; the stop letter and direction are what tell them apart, so they lead the second line.
  const sub = stop.kind === 'bus'
    ? [stop.indicator, stop.towards ? `to ${stop.towards}` : null, stop.lines.slice(0, 5).join(', ')].filter(Boolean).join(' · ')
    : stop.lines.slice(0, 5).join(' · ')
  return (
    <li>
      <button
        type="button"
        role="checkbox"
        aria-checked={selected}
        onClick={onToggle}
        disabled={disabled && !selected}
        className={cn(
          'flex min-h-14 w-full items-center gap-3 rounded-px-md border px-4 py-2.5 text-left transition-colors disabled:opacity-50',
          selected ? 'border-px-brand bg-px-brand-soft text-px-on-brand-soft' : 'border-px-border bg-px-surface hover:bg-px-surface-sunken',
        )}
      >
        <span
          className={cn(
            'flex size-6 shrink-0 items-center justify-center rounded-md border',
            selected ? 'border-px-brand bg-px-brand text-px-on-brand' : 'border-px-border-strong bg-px-surface',
          )}
          aria-hidden
        >
          {selected && <Check className="size-4" />}
        </span>
        <Icon className="size-5 shrink-0 text-px-text-secondary" aria-hidden />
        <span className="flex min-w-0 flex-1 flex-col">
          <Text variant="callout" as="span" tone="inherit" className="truncate" style={{ fontWeight: 600 }}>
            {title}
          </Text>
          {sub && (
            <Text variant="footnote" as="span" tone="secondary" className="line-clamp-2">
              {sub}
            </Text>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-1 text-px-text-secondary">
          <Footprints className="size-4" aria-hidden />
          <Text variant="footnote" as="span" tone="inherit">
            {Math.max(1, Math.round(stop.walk_min))} min
          </Text>
        </span>
      </button>
    </li>
  )
}

/** Lets the user choose which nearby stations/stops they actually use. Nothing is pre-selected. */
export function StopPicker({ lat, lon, value, onChange, placeLabel }: {
  lat: number | null
  lon: number | null
  value: ChosenStop[]
  onChange: (v: ChosenStop[]) => void
  placeLabel: string
}) {
  const { data, error, isLoading } = useNearbyStops(lat, lon)
  const chosen = new Set(value.map((s) => s.stop_id))
  const full = value.length >= MAX_STOPS
  const toggle = (s: NearbyStop) =>
    onChange(chosen.has(s.stop_id) ? value.filter((v) => v.stop_id !== s.stop_id) : [...value, toChosen(s)])

  if (lat == null || lon == null) return null
  const stations = (data ?? []).filter((s) => s.kind === 'station')
  const buses = (data ?? []).filter((s) => s.kind === 'bus').slice(0, 6)

  return (
    <div className="flex flex-col gap-4" aria-live="polite">
      <div className="flex flex-col gap-1">
        <Text variant="headline" as="h2">
          Which stations do you use?
        </Text>
        <Text variant="footnote" tone="secondary" className="text-pretty">
          Pick one or more near {placeLabel}. Paxen plans your routes from these. Skip it to let Paxen choose.
        </Text>
      </div>
      {isLoading && !data ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-14 w-full rounded-px-md" />
          <Skeleton className="h-14 w-full rounded-px-md" />
          <Skeleton className="h-14 w-full rounded-px-md" />
        </div>
      ) : error ? (
        <Text variant="footnote" tone="attention">
          Couldn&apos;t load nearby stations. You can carry on and choose them later in You.
        </Text>
      ) : !data?.length ? (
        <Text variant="footnote" tone="secondary">
          No stations or stops found nearby. Paxen will choose for you.
        </Text>
      ) : (
        <>
          {stations.length > 0 && (
            <div className="flex flex-col gap-2">
              <Text variant="subhead" as="h3" tone="secondary">
                Stations
              </Text>
              <ul className="flex flex-col gap-1.5" aria-label="Nearby stations">
                {stations.map((s) => (
                  <StopRow key={s.stop_id} stop={s} selected={chosen.has(s.stop_id)} onToggle={() => toggle(s)} disabled={full} />
                ))}
              </ul>
            </div>
          )}
          {buses.length > 0 && (
            <div className="flex flex-col gap-2">
              <Text variant="subhead" as="h3" tone="secondary">
                Bus stops
              </Text>
              <ul className="flex flex-col gap-1.5" aria-label="Nearby bus stops">
                {buses.map((s) => (
                  <StopRow key={s.stop_id} stop={s} selected={chosen.has(s.stop_id)} onToggle={() => toggle(s)} disabled={full} />
                ))}
              </ul>
            </div>
          )}
          <Text variant="footnote" tone="secondary">
            {value.length === 0
              ? 'None chosen: Paxen will pick the best stations each day.'
              : `${value.length} chosen${full ? ' (maximum)' : ''}.`}
          </Text>
        </>
      )}
    </div>
  )
}
