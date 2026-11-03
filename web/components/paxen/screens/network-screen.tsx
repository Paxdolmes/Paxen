'use client'

import { useState } from 'react'
import { AlertTriangle, ChevronDown, RefreshCw } from 'lucide-react'
import { fmtAgoSeconds } from '@/lib/format'
import { useNetwork } from '@/lib/hooks'
import type { LineStatus } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button } from '../primitives/button'
import { Card, Divider, Section, Skeleton } from '../primitives/card'
import { ErrorState } from '../primitives/states'
import { Text } from '../primitives/text'
import { LineChip, modeLabel } from '../transit/line-chip'
import { LineStatusText, SeverityDot } from '../transit/status'

const MODE_ORDER = ['tube', 'elizabeth-line', 'overground', 'dlr', 'national-rail', 'bus']

function LineRow({ line }: { line: LineStatus }) {
  const [open, setOpen] = useState(false)
  const hasReason = !!line.reason
  const content = (
    <>
      <LineChip mode={line.mode} name={line.line_name} />
      <span className="flex min-w-0 items-center gap-2">
        <SeverityDot category={line.category} />
        <LineStatusText category={line.category} description={line.description} />
        {hasReason && (
          <ChevronDown
            className={cn('size-4 shrink-0 text-px-text-tertiary transition-transform', open && 'rotate-180')}
            aria-hidden
          />
        )}
      </span>
    </>
  )
  return (
    <li>
      {hasReason ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left"
        >
          {content}
        </button>
      ) : (
        <div className="flex items-center justify-between gap-3 px-5 py-3.5">{content}</div>
      )}
      {open && line.reason && (
        <Text variant="footnote" tone="secondary" className="px-5 pb-4 text-pretty">
          {line.reason}
        </Text>
      )}
    </li>
  )
}

function LineList({ lines }: { lines: LineStatus[] }) {
  return (
    <Card>
      <ul>
        {lines.map((l, i) => (
          <div key={l.line_id}>
            {i > 0 && <Divider />}
            <LineRow line={l} />
          </div>
        ))}
      </ul>
    </Card>
  )
}

export function NetworkScreen() {
  const { data, error, isLoading, mutate, isValidating } = useNetwork()

  if (error && !data) return <ErrorState error={error} onRetry={() => mutate()} />
  if (isLoading || !data)
    return (
      <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading network status">
        <Skeleton className="h-8 w-40" />
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-40 w-full rounded-px-lg" />
        ))}
      </div>
    )

  const mine = data.lines.filter((l) => l.on_my_routes)
  const groups = new Map<string, LineStatus[]>()
  for (const l of data.lines) {
    const arr = groups.get(l.mode) ?? []
    arr.push(l)
    groups.set(l.mode, arr)
  }
  const modes = [...groups.keys()].sort(
    (a, b) => (MODE_ORDER.indexOf(a) + 1 || 99) - (MODE_ORDER.indexOf(b) + 1 || 99),
  )
  const { feed } = data

  return (
    <div className="flex flex-col gap-6">
      <Text variant="title1" as="h1" className="px-1">
        Network
      </Text>

      {mine.length > 0 && (
        <Section title="On your routes">
          <LineList lines={mine} />
        </Section>
      )}

      {modes.map((m) => (
        <Section key={m} title={modeLabel(m)}>
          <LineList lines={groups.get(m)!} />
        </Section>
      ))}

      <div className="flex items-center justify-between gap-3 px-1">
        <span className="flex items-center gap-1.5" role="status">
          {!feed.fresh && <AlertTriangle className="size-4 text-px-watch" aria-hidden />}
          <Text variant="footnote" tone={feed.fresh ? 'tertiary' : 'watch'}>
            {feed.age_s != null ? `Updated ${fmtAgoSeconds(feed.age_s)}` : 'Waiting for first update'}
            {!feed.fresh && ' · data may be out of date'}
          </Text>
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => mutate()}
          loading={isValidating}
          icon={<RefreshCw className="size-4" aria-hidden />}
        >
          Refresh
        </Button>
      </div>
    </div>
  )
}
