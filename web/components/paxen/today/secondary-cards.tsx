import { ChevronRight } from 'lucide-react'
import { fmtMin } from '@/lib/format'
import type { CommuteEvaluation, LineStatus } from '@/lib/types'
import { Card, Divider } from '../primitives/card'
import { Text } from '../primitives/text'
import { LineChip } from '../transit/line-chip'
import { CommuteStatusPill, LineStatusText, SeverityDot } from '../transit/status'

export function OtherCommuteCard({ evaluation, onOpen }: { evaluation: CommuteEvaluation; onOpen: () => void }) {
  const { commute, status, recommended } = evaluation
  return (
    <Card>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full items-center gap-4 rounded-px-lg p-5 text-left transition-colors hover:bg-px-surface-sunken/60"
      >
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center gap-2">
            <Text variant="headline" as="h3">
              {commute.name}
            </Text>
            <CommuteStatusPill status={status} />
          </div>
          <Text variant="footnote" tone="secondary" tabular className="truncate">
            {commute.window_start}–{commute.window_end} · {commute.origin.name} → {commute.dest.name}
          </Text>
        </div>
        {recommended && (
          <div className="flex flex-col items-end">
            <Text variant="title2" tabular>
              {fmtMin(recommended.duration.p50)}
            </Text>
            <Text variant="caption" tone="secondary">
              expected
            </Text>
          </div>
        )}
        <ChevronRight className="size-5 shrink-0 text-px-text-tertiary" aria-hidden />
      </button>
    </Card>
  )
}

export function LinesOnRoutes({ lines }: { lines: LineStatus[] }) {
  if (!lines.length) return null
  return (
    <Card>
      <ul>
        {lines.map((l, i) => (
          <li key={l.line_id}>
            {i > 0 && <Divider />}
            <div className="flex items-center justify-between gap-3 px-5 py-3.5">
              <LineChip mode={l.mode} name={l.line_name} />
              <span className="flex items-center gap-2">
                <SeverityDot category={l.category} />
                <LineStatusText category={l.category} description={l.description} />
              </span>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}
