import { ChevronRight, Footprints } from 'lucide-react'
import { Fragment } from 'react'
import { fmtWait } from '@/lib/format'
import type { Leg } from '@/lib/types'
import { Text } from '../primitives/text'
import { LineChip } from './line-chip'

export function LegStrip({ legs, showWait = true, muted }: { legs: Leg[]; showWait?: boolean; muted?: boolean }) {
  const firstTransit = legs.findIndex((l) => l.mode !== 'walking')
  const first = firstTransit >= 0 ? legs[firstTransit] : null
  const later = first ? first.next_departures_min.slice(1, 3).map((m) => Math.round(m)) : []

  return (
    <div className="flex flex-col gap-2">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-2" aria-label="Route legs">
        {legs.map((leg, i) => (
          <Fragment key={`${leg.mode}-${leg.from}-${i}`}>
            {i > 0 && <ChevronRight className="size-3.5 text-px-text-tertiary" aria-hidden />}
            <li className="flex items-center">
              {leg.mode === 'walking' ? (
                <span className="inline-flex items-center gap-1 text-px-text-secondary">
                  <Footprints className="size-4" aria-hidden />
                  <Text variant="footnote" as="span" tone="secondary" tabular style={{ fontWeight: 600 }}>
                    {Math.max(1, Math.round(leg.ride_min))}
                    <span className="sr-only"> minute walk</span>
                  </Text>
                </span>
              ) : (
                <LineChip
                  mode={leg.mode}
                  name={leg.line_name ?? leg.line_id ?? leg.mode}
                  live={leg.live && !muted}
                  status={leg.status}
                  muted={muted}
                />
              )}
            </li>
          </Fragment>
        ))}
      </ol>
      {showWait && first && (
        <Text variant="footnote" tone="secondary" tabular>
          <span className="text-px-text" style={{ fontWeight: 600 }}>
            {fmtWait(first.wait_min)}
          </span>
          {` at ${first.from}`}
          {later.length > 0 && <span className="text-px-text-tertiary">{` · then ${later.join(', ')}`}</span>}
          {!first.live && <span className="text-px-text-tertiary"> · scheduled</span>}
        </Text>
      )}
    </div>
  )
}
