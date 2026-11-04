'use client'

import { CalendarClock, CloudRain, Sun, Wind } from 'lucide-react'
import type { Conditions, UpcomingDisruption } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Card, Divider } from '../primitives/card'
import { Text } from '../primitives/text'
import { LineChip } from '../transit/line-chip'

/** Rain at departure and London air quality vs usual. Renders nothing when neither is known. */
export function ConditionsStrip({ conditions }: { conditions: Conditions | null | undefined }) {
  const w = conditions?.weather
  const aq = conditions?.air_quality
  if (!w && !aq) return null
  const aqBad = (aq?.level ?? 0) >= 2 || aq?.worse_than_usual
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex flex-wrap gap-x-6 gap-y-3">
        {w && (
          <div className="flex items-center gap-2">
            {w.wet ? (
              <CloudRain className="size-5 text-px-watch" aria-hidden />
            ) : (
              <Sun className="size-5 text-px-text-secondary" aria-hidden />
            )}
            <div className="flex flex-col">
              <Text variant="callout" style={{ fontWeight: 600 }} tone={w.wet ? 'watch' : 'primary'}>
                {w.summary} at {w.time}
              </Text>
              <Text variant="caption" tone="secondary" tabular>
                {[w.temp_c != null ? `${Math.round(w.temp_c)}°C` : null, w.rain_prob != null ? `${w.rain_prob}% chance of rain` : null]
                  .filter(Boolean)
                  .join(' · ')}
              </Text>
            </div>
          </div>
        )}
        {aq && (
          <div className="flex items-center gap-2">
            <Wind className={cn('size-5', aqBad ? 'text-px-attention' : 'text-px-text-secondary')} aria-hidden />
            <div className="flex flex-col">
              <Text variant="callout" style={{ fontWeight: 600 }} tone={aqBad ? 'attention' : 'primary'}>
                Air quality: {aq.band}
              </Text>
              <Text variant="caption" tone="secondary">
                {aq.usual_band ? `Usually ${aq.usual_band}` : `Learning what's usual (${aq.history_days}/7 days)`}
                {aq.tomorrow_band ? ` · Tomorrow ${aq.tomorrow_band}` : ''}
              </Text>
            </div>
          </div>
        )}
      </div>
      {conditions?.walking_note && (
        <Text variant="footnote" tone="secondary" className="text-pretty">
          {conditions.walking_note}
        </Text>
      )}
    </Card>
  )
}

/** Planned closures in the next week on lines the user's routes use. */
export function UpcomingCard({ items }: { items: UpcomingDisruption[] }) {
  if (!items.length) return null
  return (
    <Card>
      {items.map((d, i) => (
        <div key={`${d.line_id}-${d.from}`}>
          {i > 0 && <Divider />}
          <div className="flex flex-col gap-1.5 px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <LineChip mode={d.mode || 'tube'} name={d.line_name} status={d.category} />
              <Text variant="footnote" tone="attention" style={{ fontWeight: 600 }}>
                {d.description}
              </Text>
            </div>
            <Text variant="footnote" tone="primary" style={{ fontWeight: 600 }}>
              <CalendarClock className="mr-1 inline size-3.5 align-[-2px]" aria-hidden />
              From {d.starts_local}
              {d.commutes.length ? ` · affects ${d.commutes.join(' and ')}` : ''}
            </Text>
            {d.reason && (
              <Text variant="caption" tone="secondary" className="line-clamp-3 text-pretty">
                {d.reason}
              </Text>
            )}
          </div>
        </div>
      ))}
    </Card>
  )
}
