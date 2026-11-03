import { cn } from '@/lib/utils'
import { fmtTime } from '@/lib/format'

export interface TimeAxis {
  min: number
  max: number
}

/** Shared axis across options, padded and snapped to 5-minute marks. */
export function buildAxis(ranges: [string, string][]): TimeAxis | null {
  if (!ranges.length) return null
  const step = 5 * 60_000
  const lo = Math.min(...ranges.map((r) => new Date(r[0]).getTime()))
  const hi = Math.max(...ranges.map((r) => new Date(r[1]).getTime()))
  return { min: Math.floor(lo / step) * step, max: Math.ceil(hi / step) * step || lo + step }
}

const pos = (t: number, a: TimeAxis) => ((t - a.min) / Math.max(1, a.max - a.min)) * 100

export function RangeBar({
  range,
  median,
  axis,
  tone = 'brand',
}: {
  range: [string, string]
  median: string
  axis: TimeAxis
  tone?: 'brand' | 'muted' | 'attention'
}) {
  const left = pos(new Date(range[0]).getTime(), axis)
  const right = pos(new Date(range[1]).getTime(), axis)
  const mid = pos(new Date(median).getTime(), axis)
  return (
    <div
      className="relative h-2.5 w-full rounded-full bg-px-surface-sunken"
      role="img"
      aria-label={`Likely arrival between ${fmtTime(range[0])} and ${fmtTime(range[1])}, most likely ${fmtTime(median)}`}
    >
      <div
        className={cn(
          'absolute inset-y-0 rounded-full',
          tone === 'brand' && 'bg-px-brand/35',
          tone === 'muted' && 'bg-px-border-strong',
          tone === 'attention' && 'bg-px-attention/35',
        )}
        style={{ left: `${left}%`, width: `${Math.max(2, right - left)}%` }}
      />
      <div
        className={cn(
          'absolute -inset-y-0.5 w-1 -translate-x-1/2 rounded-full',
          tone === 'brand' && 'bg-px-brand',
          tone === 'muted' && 'bg-px-text-tertiary',
          tone === 'attention' && 'bg-px-attention',
        )}
        style={{ left: `${mid}%` }}
      />
    </div>
  )
}

export function AxisLabels({ axis }: { axis: TimeAxis }) {
  const span = axis.max - axis.min
  const ticks = [0, 0.5, 1].map((f) => axis.min + Math.round((span * f) / 60_000) * 60_000)
  return (
    <div className="flex justify-between text-px-text-tertiary tabular" style={{ fontSize: 12, lineHeight: '16px' }} aria-hidden>
      {ticks.map((t) => (
        <span key={t}>{fmtTime(new Date(t).toISOString())}</span>
      ))}
    </div>
  )
}
