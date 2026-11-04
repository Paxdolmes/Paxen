'use client'

import { useId, useState } from 'react'
import { Building2, Check, MapPin, Search, TrainFront } from 'lucide-react'
import { usePlaceSearch } from '@/lib/hooks'
import type { PlaceSearchResult } from '@/lib/types'
import { cn } from '@/lib/utils'
import { textStyle } from './primitives/text'
import { Text } from './primitives/text'
import { Skeleton } from './primitives/card'

const kindIcon = { station: TrainFront, address: Building2, place: MapPin } as const

export function PlaceSearch({
  label,
  placeholder,
  selected,
  onSelect,
  autoFocus,
}: {
  label: string
  placeholder: string
  selected: PlaceSearchResult | null
  onSelect: (p: PlaceSearchResult) => void
  autoFocus?: boolean
}) {
  const [q, setQ] = useState('')
  const id = useId()
  const { data, error, isLoading } = usePlaceSearch(q)
  const term = q.trim()

  return (
    <div className="flex flex-col gap-3">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <div className="relative">
        <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-px-text-tertiary" aria-hidden />
        <input
          id={id}
          type="search"
          inputMode="search"
          autoComplete="off"
          autoFocus={autoFocus}
          placeholder={placeholder}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="h-14 w-full rounded-px-md border border-px-border-strong bg-px-surface pl-12 pr-4 text-px-text placeholder:text-px-text-tertiary"
          style={textStyle('body')}
        />
      </div>

      {term.length >= 2 && (
        <div aria-live="polite">
          {isLoading && !data ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-14 w-full rounded-px-md" />
              <Skeleton className="h-14 w-full rounded-px-md" />
            </div>
          ) : error ? (
            <Text variant="footnote" tone="attention">
              Search isn&apos;t available right now. Try again in a moment.
            </Text>
          ) : data && data.length === 0 ? (
            <Text variant="footnote" tone="secondary">
              No matches for &ldquo;{term}&rdquo;. Try a full postcode (e.g. E17 9PH), a street address or a station name.
            </Text>
          ) : (
            <ul className="flex flex-col gap-1.5" aria-label="Search results">
              {data?.map((p) => {
                const Icon = kindIcon[p.kind] ?? MapPin
                const isSel = selected?.name === p.name && selected.lat === p.lat && selected.lon === p.lon
                return (
                  <li key={`${p.name}-${p.lat}-${p.lon}`}>
                    <button
                      type="button"
                      onClick={() => {
                        onSelect(p)
                        setQ('') // collapse the list; the chosen place shows below
                      }}
                      aria-pressed={isSel}
                      className={cn(
                        'flex min-h-14 w-full items-center gap-3 rounded-px-md border px-4 py-2.5 text-left transition-colors',
                        isSel
                          ? 'border-px-brand bg-px-brand-soft text-px-on-brand-soft'
                          : 'border-px-border bg-px-surface hover:bg-px-surface-sunken',
                      )}
                    >
                      <Icon className="size-5 shrink-0 text-px-text-secondary" aria-hidden />
                      <span className="flex min-w-0 flex-1 flex-col">
                        <Text variant="callout" as="span" tone="inherit" className="truncate" style={{ fontWeight: 600 }}>
                          {p.name}
                        </Text>
                        <Text variant="footnote" as="span" tone="secondary" className="truncate">
                          {p.kind === 'station' ? 'Station' : p.kind === 'address' ? 'Address' : 'Place'}
                          {p.detail ? ` · ${p.detail}` : ''}
                        </Text>
                      </span>
                      {isSel && <Check className="size-5 shrink-0 text-px-brand" aria-hidden />}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}

      {selected && term.length < 2 && (
        <div className="flex items-center gap-3 rounded-px-md border border-px-brand bg-px-brand-soft px-4 py-3 text-px-on-brand-soft">
          <Check className="size-5 shrink-0" aria-hidden />
          <Text variant="callout" tone="inherit" style={{ fontWeight: 600 }}>
            {selected.name}
          </Text>
        </div>
      )}
    </div>
  )
}
