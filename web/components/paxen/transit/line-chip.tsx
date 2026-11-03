import { Bus, Footprints, TrainFront, TrainFrontTunnel, TrainTrack, TramFront, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { modeColors } from '@/lib/paxen-tokens'
import type { LineCategory, Mode } from '@/lib/types'
import { textStyle } from '../primitives/text'

const modeIcon: Record<string, LucideIcon> = {
  tube: TrainFrontTunnel,
  overground: TrainFront,
  'elizabeth-line': TrainFront,
  'national-rail': TrainTrack,
  dlr: TramFront,
  bus: Bus,
  walking: Footprints,
}

export function ModeIcon({ mode, className }: { mode: Mode; className?: string }) {
  const Icon = modeIcon[mode] ?? TrainFront
  return <Icon className={cn('size-4', className)} aria-hidden />
}

export const modeLabel = (mode: Mode) => modeColors[mode]?.label ?? mode.replace(/-/g, ' ')

const disrupted = (s?: LineCategory) => s && s !== 'good'

export function LineChip({
  mode,
  name,
  live,
  status,
  muted,
  showIcon = true,
  className,
}: {
  mode: Mode
  name: string
  live?: boolean
  status?: LineCategory
  muted?: boolean
  showIcon?: boolean
  className?: string
}) {
  const c = modeColors[mode] ?? modeColors['national-rail']
  return (
    <span
      className={cn(
        'relative inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-px-xs px-2',
        muted && 'opacity-55 grayscale',
        className,
      )}
      style={{ background: c.bg, color: c.fg, ...textStyle('caption'), fontWeight: 600 }}
    >
      {showIcon && <ModeIcon mode={mode} className="size-3.5" />}
      <span>{name}</span>
      <span className="sr-only">{` (${modeLabel(mode)})`}</span>
      {live && (
        <span className="flex items-center" title="Live arrivals">
          <span className="px-live-dot size-1.5 rounded-full bg-px-success" aria-hidden />
          <span className="sr-only">, live</span>
        </span>
      )}
      {disrupted(status) && (
        <span
          className="absolute -right-1 -top-1 size-2.5 rounded-full border-2 border-px-surface bg-px-attention"
          aria-label="disrupted"
        />
      )}
    </span>
  )
}
