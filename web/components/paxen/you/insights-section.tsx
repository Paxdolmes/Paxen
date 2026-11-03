'use client'

import { fmtPct } from '@/lib/format'
import { useInsights } from '@/lib/hooks'
import type { Insights } from '@/lib/types'
import { Card, Divider, Section, Skeleton } from '../primitives/card'
import { ErrorState } from '../primitives/states'
import { Text } from '../primitives/text'

const LEAD_ORDER = ['0-2m', '2-5m', '5-10m', '10-20m', '20m+']
const LEAD_LABELS: Record<string, string> = {
  '0-2m': '0–2 min',
  '2-5m': '2–5 min',
  '5-10m': '5–10 min',
  '10-20m': '10–20 min',
  '20m+': '20+ min',
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-px-md bg-px-surface-sunken p-4">
      <Text variant="title2" as="span" tabular>
        {value}
      </Text>
      <Text variant="footnote" as="span" tone="secondary">
        {label}
      </Text>
      {hint && (
        <Text variant="caption" as="span" tone="tertiary">
          {hint}
        </Text>
      )}
    </div>
  )
}

function LeadChart({ byLead }: { byLead: NonNullable<Insights['model']['by_lead']> }) {
  const rows = LEAD_ORDER.filter((k) => byLead[k]).map((k) => ({ k, ...byLead[k] }))
  const max = Math.max(1, ...rows.flatMap((r) => [r.provider.mae_s ?? 0, r.corrected.mae_s ?? 0]))
  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        <Text variant="subhead" as="span">
          Average error by how far ahead
        </Text>
        <span className="flex items-center gap-3" aria-hidden>
          <span className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full bg-px-border-strong" />
            <Text variant="caption" tone="secondary">
              Countdown
            </Text>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-full bg-px-brand" />
            <Text variant="caption" tone="secondary">
              Paxen
            </Text>
          </span>
        </span>
      </figcaption>
      <ul className="flex flex-col gap-3">
        {rows.map((r) => (
          <li key={r.k} className="flex items-center gap-3">
            <Text variant="caption" tone="secondary" className="w-16 shrink-0" tabular>
              {LEAD_LABELS[r.k] ?? r.k}
            </Text>
            <div className="flex flex-1 flex-col gap-1">
              {(
                [
                  ['Countdown', r.provider.mae_s, 'bg-px-border-strong'],
                  ['Paxen', r.corrected.mae_s, 'bg-px-brand'],
                ] as const
              ).map(([name, v, cls]) =>
                v == null ? null : (
                <div key={name} className="flex items-center gap-2">
                  <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-px-surface-sunken">
                    <div className={`h-full rounded-full ${cls}`} style={{ width: `${(v / max) * 100}%` }} />
                  </div>
                  <Text variant="caption" tone="secondary" className="w-10 shrink-0 text-right" tabular>
                    <span className="sr-only">{name}: </span>
                    {Math.round(v)} s
                  </Text>
                </div>
                ),
              )}
            </div>
          </li>
        ))}
      </ul>
    </figure>
  )
}

export function InsightsSection() {
  const { data, error, isLoading, mutate } = useInsights()

  if (error && !data)
    return (
      <Section title="How Paxen is doing">
        <ErrorState error={error} onRetry={() => mutate()} />
      </Section>
    )
  if (isLoading || !data)
    return (
      <Section title="How Paxen is doing">
        <Skeleton className="h-72 w-full rounded-px-lg" />
      </Section>
    )

  const { personal: p, model: m } = data
  const ratedUseful = p.alerts_rated > 0 ? `${p.alerts_rated_useful} of ${p.alerts_rated}` : 'Not rated yet'

  return (
    <Section title="How Paxen is doing">
      <Card className="flex flex-col gap-4 p-5">
        <Text variant="headline" as="h3">
          For you · last {p.window_days} days
        </Text>
        <div className="grid grid-cols-2 gap-2">
          <Stat label="Trips logged" value={String(p.trips)} />
          <Stat label="Minutes saved" value={String(Math.round(p.minutes_saved))} />
          <Stat label="Alerts rated useful" value={ratedUseful} />
          <Stat
            label="Forecast hit rate"
            value={p.interval_hit_rate != null ? fmtPct(p.interval_hit_rate) : '—'}
            hint={p.interval_hit_rate != null ? 'Arrived within our range' : 'Learning your routine'}
          />
        </div>
      </Card>

      <Card className="flex flex-col gap-4 p-5">
        <div className="flex flex-col gap-1">
          <Text variant="headline" as="h3">
            Arrival predictions
          </Text>
          <Text variant="footnote" tone="secondary" className="text-pretty">
            Live countdowns tend to under-estimate long waits. Paxen measures what actually happened and corrects for it.
          </Text>
        </div>

        {m.status === 'no_model' || !m.provider || !m.corrected ? (
          <Text variant="callout" tone="secondary">
            {m.message ?? 'Still collecting arrivals to train the correction model.'}
          </Text>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2">
              <Stat
                label="Countdown error"
                value={m.provider.mae_s != null ? `${Math.round(m.provider.mae_s)} s` : '—'}
                hint={m.provider.within_2m != null ? `${fmtPct(m.provider.within_2m)} within 2 min` : undefined}
              />
              <Stat
                label="Paxen error"
                value={m.corrected.mae_s != null ? `${Math.round(m.corrected.mae_s)} s` : '—'}
                hint={m.corrected.within_2m != null ? `${fmtPct(m.corrected.within_2m)} within 2 min` : undefined}
              />
            </div>
            {m.by_lead && Object.keys(m.by_lead).length > 0 && (
              <>
                <Divider />
                <LeadChart byLead={m.by_lead} />
              </>
            )}
            <Text variant="caption" tone="tertiary">
              Based on {m.corrected.n.toLocaleString('en-GB')} observed arrivals
              {m.status === 'shadow' ? ' · running in shadow mode' : ''}.
            </Text>
          </>
        )}
      </Card>
    </Section>
  )
}
