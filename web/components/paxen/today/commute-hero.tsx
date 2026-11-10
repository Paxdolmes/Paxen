'use client'

import { ArrowRight, Play, Sparkles } from 'lucide-react'
import { fmtMin, fmtTime, fareLabel } from '@/lib/format'
import { useActiveTrip } from '@/lib/hooks'
import { crowdingWords, usuallyRange } from '@/lib/plain'
import type { CommuteEvaluation } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '../primitives/button'
import { Card } from '../primitives/card'
import { Chip } from '../primitives/chip'
import { Disclosure } from '../primitives/disclosure'
import { Text } from '../primitives/text'
import { ConfidenceBadge } from '../transit/confidence-badge'
import { DisruptionNote } from '../transit/disruption-note'
import { LegStrip } from '../transit/leg-strip'
import { commuteStatusMeta, CrowdingChip } from '../transit/status'
import { useStartTrip } from '../use-trip-actions'
import { TripInProgress } from './trip-in-progress'

function TimeBlock({ label, time }: { label: string; time: string }) {
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <Text variant="subhead" tone="secondary" style={{ fontWeight: 600 }}>
        {label}
      </Text>
      <Text variant="display" as="p" tabular>
        {time}
      </Text>
    </div>
  )
}

export function CommuteHero({ evaluation, onCompare, onLive }: { evaluation: CommuteEvaluation; onCompare: () => void; onLive: () => void }) {
  const { commute, status, headline, detail, recommended: rec, usual, baseline, delta_min } = evaluation
  const meta = commuteStatusMeta[status]
  const StatusIcon = meta.icon
  const activeTrip = useActiveTrip()
  const { start, pending, error } = useStartTrip()
  const tripHere = activeTrip?.commute_id === commute.id ? activeTrip : null

  const switched = rec && usual && rec.id !== usual.id
  const gain = evaluation.gain_min ?? (rec?.vs_usual_min != null ? -rec.vs_usual_min : null)
  const slowerBy = delta_min != null && Math.round(delta_min) > 0 ? Math.round(delta_min) : null
  const range = rec ? usuallyRange(rec.duration.p10, rec.duration.p90) : null

  return (
    <Card className="overflow-hidden" aria-labelledby={`hero-${commute.id}`}>
      <div className={cn('flex flex-col gap-2 px-5 pb-5 pt-4', meta.headerClass)}>
        <div className="flex items-center justify-between gap-3">
          <span className="inline-flex min-w-0 items-center gap-1.5">
            <StatusIcon className="size-4 shrink-0" aria-hidden />
            <Text variant="footnote" tone="inherit" className="truncate" style={{ fontWeight: 700 }}>
              {meta.label}
            </Text>
          </span>
          <Text variant="footnote" tone="inherit" tabular className="shrink-0 opacity-90">
            {commute.name} · {commute.window_start}–{commute.window_end}
          </Text>
        </div>
        <Text id={`hero-${commute.id}`} variant="title1" as="h2" tone="inherit" className="text-balance">
          {headline}
        </Text>
        {detail && (
          <Text variant="subhead" tone="inherit" className="text-pretty">
            {detail}
          </Text>
        )}
        {evaluation.chosen_stops_honoured === false && (
          <Text variant="footnote" tone="inherit" className="text-pretty">
            Nothing is running from your chosen stations right now, so these routes use other stations.
          </Text>
        )}
      </div>

      <div className="flex flex-col gap-5 p-5">
        {tripHere ? (
          <TripInProgress trip={tripHere} onOpen={onLive} />
        ) : rec ? (
          <>
            <div className="flex flex-col gap-2">
              <div className="flex items-start gap-4">
                <TimeBlock label="Leave by" time={fmtTime(rec.depart_at)} />
                <TimeBlock label="Arrive about" time={fmtTime(rec.arrive_at)} />
              </div>
              <Text variant="subhead" tone="secondary" tabular>
                {fmtMin(rec.duration.p50)} door to door
                {range ? ` \u00b7 ${range}` : ''}
              </Text>
              {slowerBy != null && (
                <div>
                  <Chip tone="attention" size="md" className="tabular">
                    {slowerBy} min slower than usual
                  </Chip>
                </div>
              )}
            </div>

            {switched && (
              <div className="flex items-start gap-2 rounded-px-md bg-px-brand-soft p-4 text-px-on-brand-soft">
                <Sparkles className="mt-0.5 size-4 shrink-0" aria-hidden />
                <Text variant="callout" as="p" tone="inherit" className="text-pretty" style={{ fontWeight: 600 }}>
                  Better today: take {rec.summary}
                  {gain != null && Math.round(gain) > 0 && ` \u2014 ${Math.round(gain)} min sooner`}
                </Text>
              </div>
            )}

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
                See other routes
              </Button>
              {error && (
                <Text variant="footnote" tone="attention" role="alert">
                  {error}
                </Text>
              )}
            </div>

            <Disclosure label="Route details" openLabel="Hide route details" className="border-t border-px-border pt-1">
              <div className="flex flex-col gap-2">
                <Text variant="subhead" tone="secondary" style={{ fontWeight: 600 }}>
                  {switched ? 'Recommended route' : 'Your route'}
                </Text>
                <LegStrip legs={rec.legs} />
              </div>

              {switched && usual && (
                <div className="flex flex-col gap-2 rounded-px-md border border-dashed border-px-border-strong p-3">
                  <div className="flex items-center justify-between gap-2">
                    <Text variant="footnote" tone="secondary">
                      Your usual: <span className="line-through">{usual.summary}</span>
                    </Text>
                    <Text variant="footnote" tone="secondary" tabular>
                      {usual.feasible ? fmtMin(usual.duration.p50) : 'Not running'}
                    </Text>
                  </div>
                  <LegStrip legs={usual.legs} showWait={false} muted />
                  {usual.disruptions.map((d) => (
                    <DisruptionNote key={d.line_id} disruption={d} withReason={false} />
                  ))}
                </div>
              )}

              {rec.disruptions.length > 0 && (
                <div className="flex flex-col gap-2">
                  {rec.disruptions.map((d) => (
                    <DisruptionNote key={d.line_id} disruption={d} />
                  ))}
                </div>
              )}

              <div className="flex flex-col gap-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <ConfidenceBadge confidence={rec.confidence} />
                  <CrowdingChip crowding={rec.crowding} />
                </div>
                {rec.crowding.level !== 'n/a' && (
                  <Text variant="footnote" tone="secondary" className="text-pretty">
                    {crowdingWords(rec.crowding.basis)}
                  </Text>
                )}
              </div>

              <Text variant="footnote" tone="secondary" tabular>
                {baseline.p50 != null ? (
                  <>
                    <span className="text-px-text" style={{ fontWeight: 600 }}>
                      Usually {fmtMin(baseline.p50)}
                    </span>
                    {` \u00b7 ${baseline.label}`}
                  </>
                ) : (
                  <>{`Still learning your usual trip \u00b7 ${baseline.label}`}</>
                )}
                {rec.fare ? ` \u00b7 Fare ${fareLabel(rec.fare)}` : ''}
              </Text>
            </Disclosure>
          </>
        ) : (
          <div className="flex flex-col gap-3">
            <Text variant="body" tone="secondary">
              No route is available for this journey right now.
            </Text>
            <Button variant="secondary" block onClick={onCompare}>
              See other routes
            </Button>
          </div>
        )}
      </div>
    </Card>
  )
}
