'use client'

import { useState } from 'react'
import { Ban, ChevronDown, Footprints, Pin, Play, Repeat2 } from 'lucide-react'
import { fmtMin, fmtTime, fareLabel } from '@/lib/format'
import { crowdingWords, newDelayRiskWords, onTimeWords, waitBasisHint } from '@/lib/plain'
import type { RouteOption } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '../primitives/button'
import { Card, Divider } from '../primitives/card'
import { Chip } from '../primitives/chip'
import { Text } from '../primitives/text'
import { ConfidenceBadge } from '../transit/confidence-badge'
import { DisruptionNote } from '../transit/disruption-note'
import { LineChip, ModeIcon } from '../transit/line-chip'
import { RangeBar, type TimeAxis } from '../transit/range-bar'
import { CrowdingChip } from '../transit/status'

function vsUsual(min: number | null, isUsual: boolean) {
  if (isUsual || min == null) return null
  const m = Math.round(min)
  if (m === 0) return { text: 'Same as usual', tone: 'secondary' as const }
  return m < 0
    ? { text: `${Math.abs(m)} min faster than usual`, tone: 'success' as const }
    : { text: `${m} min slower than usual`, tone: 'secondary' as const }
}

export function OptionCard({
  option,
  axis,
  onStart,
  onMakeUsual,
  starting,
  savingUsual,
  canStart,
}: {
  option: RouteOption
  axis: TimeAxis | null
  onStart: () => void
  onMakeUsual: () => void
  starting: boolean
  savingUsual: boolean
  canStart: boolean
}) {
  const [open, setOpen] = useState(false)
  const transit = option.legs.filter((l) => l.mode !== 'walking')
  const vs = vsUsual(option.vs_usual_min, option.is_usual)
  const off = !option.feasible
  const onTime = onTimeWords(option.on_time_chance)
  const riskText = newDelayRiskWords(option.disruption_risk)
  const panelId = `opt-${option.id.replace(/[^a-z0-9]/gi, '')}`

  return (
    <Card className={cn('overflow-hidden', option.is_recommended && 'ring-2 ring-px-brand', off && 'opacity-70')}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full flex-col gap-3 p-5 pb-3 text-left"
      >
        <div className="flex w-full items-start justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {option.is_recommended && <Chip tone="brand">Recommended</Chip>}
            {option.is_usual && <Chip tone="outline">Usual</Chip>}
            {off && (
              <Chip tone="attention" icon={<Ban className="size-3.5" aria-hidden />}>
                Not running
              </Chip>
            )}
          </div>
          <ChevronDown
            className={cn('size-5 shrink-0 text-px-text-tertiary transition-transform', open && 'rotate-180')}
            aria-hidden
          />
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {transit.map((l, i) => (
            <LineChip key={`${l.line_id}-${i}`} mode={l.mode} name={l.line_name ?? l.mode} status={l.status} muted={off} />
          ))}
          <span className="sr-only">{option.summary}</span>
        </div>

        <div className="flex w-full items-end justify-between gap-3">
          <div className="flex flex-col">
            <Text variant="caption" tone="secondary">
              Arrive
            </Text>
            <Text variant="title1" as="p" tabular className={cn(off && 'line-through')}>
              {fmtTime(option.arrive_at)}
            </Text>
          </div>
          <div className="flex flex-col items-end">
            <Text variant="headline" as="p" tabular>
              {fmtMin(option.duration.p50)}
            </Text>
            {vs && (
              <Text variant="footnote" tone={vs.tone} tabular style={{ fontWeight: 600 }}>
                {vs.text}
              </Text>
            )}
          </div>
        </div>

        {axis && !off && (
          <div className="flex w-full flex-col gap-1">
            <RangeBar
              range={option.arrive_range}
              median={option.arrive_at}
              axis={axis}
              tone={option.is_recommended ? 'brand' : option.disruptions.length ? 'attention' : 'muted'}
            />
            <Text variant="caption" tone="secondary" tabular>
              Likely between {fmtTime(option.arrive_range[0])} and {fmtTime(option.arrive_range[1])}
            </Text>
          </div>
        )}

        <div className="flex w-full flex-wrap gap-x-4 gap-y-1 text-px-text-secondary">
          <Meta icon={<Footprints className="size-3.5" aria-hidden />}>{fmtMin(option.walking_min)} walk</Meta>
          <Meta icon={<Repeat2 className="size-3.5" aria-hidden />}>
            {option.changes === 0 ? 'Direct' : `${option.changes} change${option.changes > 1 ? 's' : ''}`}
          </Meta>
          {!off && onTime && (
            <span
              className={cn(
                onTime.tone === 'success' && 'text-px-success',
                onTime.tone === 'watch' && 'text-px-watch',
                onTime.tone === 'attention' && 'text-px-attention',
              )}
            >
              <Meta>{onTime.text}</Meta>
            </span>
          )}
          {option.reliability && <Meta>{option.reliability.label}</Meta>}
          {option.fare && <Meta>{fareLabel(option.fare)}</Meta>}
        </div>
      </button>

      <div className="flex flex-col gap-2 px-5 pb-4">
        <div className="flex flex-wrap items-center gap-2">
          <ConfidenceBadge confidence={option.confidence} />
          <CrowdingChip crowding={option.crowding} />
        </div>
        {option.disruptions.map((d) => (
          <DisruptionNote key={d.line_id} disruption={d} />
        ))}
        {riskText && !off && (
          <Text variant="footnote" tone="secondary" className="text-pretty">
            {riskText}
          </Text>
        )}
      </div>

      {open && (
        <div id={panelId} className="flex flex-col gap-4 px-5 pb-5">
          <Divider />
          <ol className="flex flex-col gap-3">
            {option.legs.map((leg, i) => (
              <li key={`${leg.from}-${i}`} className="flex gap-3">
                <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-px-surface-sunken text-px-text-secondary">
                  <ModeIcon mode={leg.mode} />
                </span>
                <div className="flex min-w-0 flex-col gap-0.5">
                  {leg.mode === 'walking' ? (
                    <Text variant="callout">
                      Walk {fmtMin(leg.ride_min)} to {leg.to}
                    </Text>
                  ) : (
                    <>
                      <Text variant="callout" style={{ fontWeight: 600 }}>
                        {leg.line_name}
                        {leg.direction ? ` towards ${leg.direction}` : ''}
                      </Text>
                      <Text variant="footnote" tone="secondary">
                        {leg.from} → {leg.to}
                      </Text>
                      <Text variant="footnote" tone="secondary" tabular>
                        Wait {fmtMin(leg.wait_min)} · ride {fmtMin(leg.ride_min)} ·{' '}
                        <span className={waitBasisHint(leg).live ? 'text-px-success' : undefined} style={{ fontWeight: 600 }}>
                          {waitBasisHint(leg).label}
                        </span>
                      </Text>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ol>
          {option.crowding.basis && (
            <Text variant="caption" tone="secondary">
              {crowdingWords(option.crowding.basis)}
            </Text>
          )}
          {!off && (
            <div className="flex flex-col gap-2">
              {canStart && (
                <Button block onClick={onStart} loading={starting} icon={<Play className="size-4 fill-current" aria-hidden />}>
                  I&apos;m leaving now
                </Button>
              )}
              {!option.is_usual && (
                <Button
                  variant="secondary"
                  block
                  onClick={onMakeUsual}
                  loading={savingUsual}
                  icon={<Pin className="size-4" aria-hidden />}
                >
                  Make this my usual route
                </Button>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

function Meta({ icon, children }: { icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 tabular" style={{ fontSize: 14, lineHeight: '20px', fontWeight: 500 }}>
      {icon}
      {children}
    </span>
  )
}
