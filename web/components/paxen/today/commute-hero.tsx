'use client'

import { ArrowRight, Play, Sparkles } from 'lucide-react'
import { fmtDelta, fmtMin, fmtTime, fareLabel } from '@/lib/format'
import { useActiveTrip } from '@/lib/hooks'
import type { CommuteEvaluation } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '../primitives/button'
import { Card, Divider } from '../primitives/card'
import { Chip } from '../primitives/chip'
import { Text } from '../primitives/text'
import { ConfidenceBadge } from '../transit/confidence-badge'
import { LegStrip } from '../transit/leg-strip'
import { commuteStatusMeta, CrowdingChip } from '../transit/status'
import { useStartTrip } from '../use-trip-actions'
import { TripInProgress } from './trip-in-progress'

export function CommuteHero({ evaluation, onCompare, onLive }: { evaluation: CommuteEvaluation; onCompare: () => void; onLive: () => void }) {
  const { commute, status, headline, detail, recommended: rec, usual, baseline, delta_min } = evaluation
  const meta = commuteStatusMeta[status]
  const StatusIcon = meta.icon
  const activeTrip = useActiveTrip()
  const { start, pending, error } = useStartTrip()
  const tripHere = activeTrip?.commute_id === commute.id ? activeTrip : null

  const switched = rec && usual && rec.id !== usual.id
  const gain = evaluation.gain_min ?? (rec?.vs_usual_min != null ? -rec.vs_usual_min : null)
  const delta = delta_min != null && Math.round(delta_min) > 0 ? fmtDelta(delta_min) : null

  return (
    <Card className="overflow-hidden" aria-labelledby={`hero-${commute.id}`}>
      <div className={cn('flex flex-col gap-2 px-5 pb-5 pt-4', meta.headerClass)}>
        <div className="flex items-center justify-between gap-3">
          <span className="inline-flex items-center gap-1.5">
            <StatusIcon className="size-4" aria-hidden />
            <Text variant="footnote" tone="inherit" style={{ fontWeight: 700 }}>
              {commute.name} · {commute.window_start}–{commute.window_end}
            </Text>
          </span>
          <Text variant="caption" tone="inherit" className="uppercase" style={{ fontWeight: 700, letterSpacing: 0.6 }}>
            {meta.label}
          </Text>
        </div>
        <Text id={`hero-${commute.id}`} variant="title1" as="h2" tone="inherit" className="text-balance">
          {headline}
        </Text>
        {detail && (
          <Text variant="subhead" tone="inherit" className="text-pretty opacity-90">
            {detail}
          </Text>
        )}
        {evaluation.chosen_stops_honoured === false && (
          <Text variant="footnote" tone="inherit" className="text-pretty opacity-90">
            Nothing is running from your chosen stations right now, so these routes use other stations.
          </Text>
        )}
      </div>

      <div className="flex flex-col gap-5 p-5">
        {tripHere ? (
          <TripInProgress trip={tripHere} onOpen={onLive} />
        ) : rec ? (
          <>
            <div className="flex items-end justify-between gap-4">
              <div className="flex flex-col">
                <Text variant="caption" tone="secondary">
                  Arrive
                </Text>
                <Text variant="display" tabular>
                  ~{fmtTime(rec.arrive_at)}
                </Text>
                <Text variant="footnote" tone="secondary" tabular>
                  Likely {fmtTime(rec.arrive_range[0])}–{fmtTime(rec.arrive_range[1])}
                </Text>
              </div>
              <div className="flex flex-col items-end gap-1">
                <Text variant="title2" tabular>
                  {fmtMin(rec.duration.p50)}
                </Text>
                <Text variant="caption" tone="secondary">
                  door to door
                </Text>
                {delta && (
                  <Chip tone="attention" className="tabular">
                    {switched ? `Usual ${delta}` : delta} vs normal
                  </Chip>
                )}
              </div>
            </div>

            <Text variant="footnote" tone="secondary" tabular>
              {baseline.p50 != null ? (
                <>
                  <span className="text-px-text" style={{ fontWeight: 600 }}>
                    Normal: {fmtMin(baseline.p50)}
                  </span>
                  {` · ${baseline.label}`}
                </>
              ) : (
                <>Learning your routine · {baseline.label}</>
              )}
              {rec.fare ? ` · Fare ${fareLabel(rec.fare)}` : ''}
            </Text>

            <Divider />

            {switched && (
              <div className="flex flex-col gap-3 rounded-px-md bg-px-brand-soft p-4 text-px-on-brand-soft">
                <div className="flex items-start gap-2">
                  <Sparkles className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <div className="flex flex-col gap-0.5">
                    <Text variant="caption" tone="inherit" className="uppercase" style={{ fontWeight: 700, letterSpacing: 0.6 }}>
                      Better today
                    </Text>
                    <Text variant="headline" as="p" tone="inherit" className="text-pretty">
                      Take {rec.summary}
                      {gain != null && Math.round(gain) > 0 && ` — ${Math.round(gain)} min sooner`}
                    </Text>
                  </div>
                </div>
              </div>
            )}

            <div className="flex flex-col gap-2">
              <Text variant="caption" tone="secondary">
                {switched ? 'Recommended route' : 'Your route'}
              </Text>
              <LegStrip legs={rec.legs} />
            </div>

            {switched && usual && (
              <div className="flex flex-col gap-2 rounded-px-md border border-dashed border-px-border-strong p-3">
                <div className="flex items-center justify-between gap-2">
                  <Text variant="footnote" tone="secondary">
                    Usual: <span className="line-through">{usual.summary}</span>
                  </Text>
                  <Text variant="footnote" tone="tertiary" tabular>
                    {usual.feasible ? fmtMin(usual.duration.p50) : 'Not running'}
                  </Text>
                </div>
                <LegStrip legs={usual.legs} showWait={false} muted />
                {usual.disruptions.map((d) => (
                  <Text key={d.line_id} variant="footnote" tone="attention" className="text-pretty">
                    {d.line_name}: {d.description}
                  </Text>
                ))}
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <ConfidenceBadge confidence={rec.confidence} />
                <CrowdingChip crowding={rec.crowding} />
              </div>
              {rec.crowding.level !== 'n/a' && (
                <Text variant="caption" tone="tertiary" className="text-pretty">
                  Crowding is an estimate{rec.crowding.basis ? ` · ${rec.crowding.basis}` : ''}
                </Text>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <Button
                block
                onClick={async () => {
                  if (await start(commute.id, rec)) onLive()
                }}
                loading={pending === rec.id}
                disabled={!rec.feasible}
                icon={<Play className="size-4 fill-current" aria-hidden />}
              >
                I&apos;m leaving now
              </Button>
              <Button variant="secondary" block onClick={onCompare} icon={<ArrowRight className="size-4" aria-hidden />}>
                Compare routes
              </Button>
              {error && (
                <Text variant="footnote" tone="attention" role="alert">
                  {error}
                </Text>
              )}
            </div>
          </>
        ) : (
          <div className="flex flex-col gap-3">
            <Text variant="body" tone="secondary">
              No route is available for this journey right now.
            </Text>
            <Button variant="secondary" block onClick={onCompare}>
              Compare routes
            </Button>
          </div>
        )}
      </div>
    </Card>
  )
}
