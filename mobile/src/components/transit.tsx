import { Fragment, useState, type ComponentType } from 'react'
import { Pressable, View } from 'react-native'
import {
  Bus,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  Footprints,
  Gauge,
  TrainFront,
  TrainFrontTunnel,
  TrainTrack,
  TramFront,
  TriangleAlert,
  Users,
} from 'lucide-react-native'
import { fmtTime, fmtWait } from '@/shared/format'
import { modeColors, radii } from '@/shared/paxen-tokens'
import { CONFIDENCE_PLAIN, stillOnChance, stillOnWords, waitBasisHint } from '@/shared/plain'
import type { CommuteStatus, Confidence, Disruption, Leg, LineCategory, Mode, RouteOption } from '@/shared/types'
import { WORDMARK_FONT } from '@/lib/fonts'
import { alpha, usePalette, type Palette } from '@/lib/theme'
import { Sheet } from './sheet'
import { Text } from './text'
import { Button, Chip, type ChipTone } from './ui'

type Icon = ComponentType<{ size?: number; color?: string; strokeWidth?: number }>

/* ---------- wordmark ---------- */

/** Text wordmark: lowercase, tight, with a "signal" dot that reads as on-time. */
/** Roman serif capitals, widely tracked, with a short crimson rule beneath (the crest's "PAX" lettering). */
export function Wordmark({ size = 22 }: { size?: number }) {
  const p = usePalette()
  return (
    <View accessible accessibilityRole="header" accessibilityLabel="Paxen" style={{ alignItems: 'flex-start', gap: size * 0.16 }}>
      <Text
        style={{ fontFamily: WORDMARK_FONT, fontSize: size, lineHeight: size * 1.15, letterSpacing: 0.16 * size, marginRight: -0.16 * size, color: p.text }}
      >
        PAXEN
      </Text>
      <View style={{ width: size * 1.1, height: Math.max(2, Math.round(size * 0.09)), borderRadius: size, backgroundColor: p.accent }} />
    </View>
  )
}

/* ---------- lines ---------- */

const modeIcon: Record<string, Icon> = {
  tube: TrainFrontTunnel,
  overground: TrainFront,
  'elizabeth-line': TrainFront,
  'national-rail': TrainTrack,
  dlr: TramFront,
  bus: Bus,
  walking: Footprints,
}

export function ModeIcon({ mode, size = 16, color }: { mode: Mode; size?: number; color?: string }) {
  const I = modeIcon[mode] ?? TrainFront
  return <I size={size} color={color} />
}

export const modeLabel = (mode: Mode) => modeColors[mode]?.label ?? mode.replace(/-/g, ' ')

export function LineChip({ mode, name, live, status, muted, showIcon = true }: { mode: Mode; name: string; live?: boolean; status?: LineCategory; muted?: boolean; showIcon?: boolean }) {
  const p = usePalette()
  const c = modeColors[mode] ?? modeColors['national-rail']
  return (
    <View
      accessibilityLabel={`${name} (${modeLabel(mode)})${live ? ', live' : ''}${status && status !== 'good' ? ', disrupted' : ''}`}
      style={{
        height: 28,
        paddingHorizontal: 8,
        borderRadius: radii.xs,
        backgroundColor: muted ? p.textTertiary : c.bg,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        opacity: muted ? 0.6 : 1,
        alignSelf: 'flex-start',
      }}
    >
      {showIcon && <ModeIcon mode={mode} size={14} color={c.fg} />}
      <Text variant="caption" color={c.fg} style={{ fontWeight: '600' }} numberOfLines={1}>
        {name}
      </Text>
      {live && <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: p.success }} />}
      {status && status !== 'good' && (
        <View style={{ position: 'absolute', right: -4, top: -4, width: 10, height: 10, borderRadius: 5, borderWidth: 2, borderColor: p.surface, backgroundColor: p.attention }} />
      )}
    </View>
  )
}

export function LegStrip({ legs, showWait = true, muted }: { legs: Leg[]; showWait?: boolean; muted?: boolean }) {
  const p = usePalette()
  const first = legs.find((l) => l.mode !== 'walking') ?? null
  const later = first ? first.next_departures_min.slice(1, 3).map((m) => Math.round(m)) : []
  const basis = waitBasisHint(first ?? { wait_basis: null, live: false })
  return (
    <View style={{ gap: 8 }}>
      <View accessibilityLabel="Route legs" style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', columnGap: 4, rowGap: 8 }}>
        {legs.map((leg, i) => (
          <Fragment key={`${leg.mode}-${leg.from}-${i}`}>
            {i > 0 && <ChevronRight size={14} color={p.textTertiary} />}
            {leg.mode === 'walking' ? (
              <View accessibilityLabel={`${Math.max(1, Math.round(leg.ride_min))} minute walk`} style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                <Footprints size={16} color={p.textSecondary} />
                <Text variant="footnote" tone="secondary" tabular style={{ fontWeight: '600' }}>
                  {Math.max(1, Math.round(leg.ride_min))}
                </Text>
              </View>
            ) : (
              <LineChip mode={leg.mode} name={leg.line_name ?? leg.line_id ?? leg.mode} live={leg.live && !muted} status={leg.status} muted={muted} />
            )}
          </Fragment>
        ))}
      </View>
      {showWait && first && (
        <Text variant="footnote" tone="secondary" tabular>
          <Text variant="footnote" style={{ fontWeight: '600' }}>
            {fmtWait(first.wait_min)}
          </Text>
          {` at ${first.from}`}
          {later.length > 0 && <Text variant="footnote" tone="tertiary">{` · then ${later.join(', ')}`}</Text>}
          <Text variant="footnote" tone={basis.live ? 'success' : 'tertiary'}>{` · ${basis.label}`}</Text>
        </Text>
      )}
    </View>
  )
}

/* ---------- confidence, disruption ---------- */

const confTone = (p: Palette, c: Confidence) =>
  ({ high: { bg: p.brandSoft, fg: p.onBrandSoft }, medium: { bg: p.watchSoft, fg: p.onWatchSoft }, low: { bg: p.surfaceSunken, fg: p.textSecondary } })[c]

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const p = usePalette()
  const [open, setOpen] = useState(false)
  const { label, meaning } = CONFIDENCE_PLAIN[confidence]
  const t = confTone(p, confidence)
  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}. Tap to learn what this means.`}
        onPress={() => setOpen(true)}
        hitSlop={8}
        style={{ height: 28, paddingHorizontal: 12, borderRadius: radii.pill, backgroundColor: t.bg, flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start' }}
      >
        <Gauge size={14} color={t.fg} />
        <Text variant="caption" color={t.fg} style={{ fontWeight: '600' }}>
          {label}
        </Text>
      </Pressable>
      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title={label}
        footer={
          <Button variant="secondary" block onPress={() => setOpen(false)}>
            Got it
          </Button>
        }
      >
        <Text variant="body">{meaning}</Text>
        <Text variant="subhead" tone="secondary">
          Based on live arrivals, what usually happens on this route, and today&apos;s disruption.
        </Text>
      </Sheet>
    </>
  )
}

export function DisruptionNote({ disruption: d, withReason = true }: { disruption: Disruption; withReason?: boolean }) {
  const outlook = stillOnWords(stillOnChance(d))
  return (
    <View style={{ gap: 2 }}>
      <Text variant="footnote" tone="attention">
        <Text variant="footnote" tone="attention" style={{ fontWeight: '600' }}>
          {d.line_name}:
        </Text>{' '}
        {d.description}
        {withReason && d.reason ? ` — ${d.reason}` : ''}
      </Text>
      {outlook && (
        <Text variant="footnote" tone="secondary">
          {outlook}
        </Text>
      )}
    </View>
  )
}

/* ---------- status ---------- */

export const commuteStatusMeta = (p: Palette): Record<CommuteStatus, { label: string; tone: ChipTone; bg: string; fg: string; icon: Icon }> => ({
  normal: { label: 'All good', tone: 'success', bg: p.successSoft, fg: p.onSuccessSoft, icon: CircleCheck },
  watch: { label: 'Keep an eye on it', tone: 'watch', bg: p.watchSoft, fg: p.onWatchSoft, icon: TriangleAlert },
  slower: { label: 'Slower than usual', tone: 'attention', bg: p.attentionSoft, fg: p.onAttentionSoft, icon: CircleAlert },
  disrupted: { label: 'Disrupted', tone: 'attentionStrong', bg: p.attention, fg: p.onAttention, icon: CircleAlert },
  unknown: { label: 'Still learning', tone: 'neutral', bg: p.surfaceSunken, fg: p.text, icon: CircleHelp },
})

export function CommuteStatusPill({ status }: { status: CommuteStatus }) {
  const p = usePalette()
  const m = commuteStatusMeta(p)[status]
  const I = m.icon
  return (
    <Chip tone={m.tone} icon={(c) => <I size={14} color={c} />}>
      {m.label}
    </Chip>
  )
}

export const lineCategoryTone: Record<LineCategory, 'success' | 'watch' | 'attention'> = {
  good: 'success',
  minor: 'watch',
  severe: 'attention',
  part_suspended: 'attention',
  suspended: 'attention',
}

export function SeverityDot({ category }: { category: LineCategory }) {
  const p = usePalette()
  return <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: p[lineCategoryTone[category]] }} />
}

export function LineStatusText({ category, description }: { category: LineCategory; description: string }) {
  return (
    <Text variant="subhead" tone={lineCategoryTone[category]} style={{ fontWeight: '600', flexShrink: 1 }}>
      {description}
    </Text>
  )
}

const crowdTone: Record<RouteOption['crowding']['level'], ChipTone> = {
  quiet: 'success',
  typical: 'neutral',
  busy: 'watch',
  busier: 'watch',
  very_busy: 'attention',
  'n/a': 'neutral',
}

export function CrowdingChip({ crowding }: { crowding: RouteOption['crowding'] }) {
  if (crowding.level === 'n/a') return null
  return (
    <View accessibilityLabel={`Estimated crowding: ${crowding.label}`}>
      <Chip tone={crowdTone[crowding.level]} icon={(c) => <Users size={14} color={c} />}>
        {crowding.label}
      </Chip>
    </View>
  )
}

/* ---------- arrival range bar ---------- */

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

export function RangeBar({ range, median, axis, tone = 'brand' }: { range: [string, string]; median: string; axis: TimeAxis; tone?: 'brand' | 'accent' | 'muted' | 'attention' }) {
  const p = usePalette()
  const left = pos(new Date(range[0]).getTime(), axis)
  const right = pos(new Date(range[1]).getTime(), axis)
  const mid = pos(new Date(median).getTime(), axis)
  const solid = tone === 'brand' ? p.brand : tone === 'accent' ? p.accent : tone === 'attention' ? p.attention : p.textTertiary
  const soft = tone === 'muted' ? p.borderStrong : alpha(solid, 0.35)
  return (
    <View
      accessibilityRole="image"
      accessibilityLabel={`Likely arrival between ${fmtTime(range[0])} and ${fmtTime(range[1])}, most likely ${fmtTime(median)}`}
      style={{ height: 10, borderRadius: 5, backgroundColor: p.surfaceSunken }}
    >
      <View style={{ position: 'absolute', top: 0, bottom: 0, left: `${left}%`, width: `${Math.max(2, right - left)}%`, borderRadius: 5, backgroundColor: soft }} />
      <View style={{ position: 'absolute', top: -2, bottom: -2, left: `${mid}%`, width: 4, marginLeft: -2, borderRadius: 2, backgroundColor: solid }} />
    </View>
  )
}

export function AxisLabels({ axis }: { axis: TimeAxis }) {
  const span = axis.max - axis.min
  const ticks = [0, 0.5, 1].map((f) => axis.min + Math.round((span * f) / 60_000) * 60_000)
  return (
    <View importantForAccessibility="no-hide-descendants" style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
      {ticks.map((t) => (
        <Text key={t} tone="tertiary" tabular style={{ fontSize: 12, lineHeight: 16 }}>
          {fmtTime(new Date(t).toISOString())}
        </Text>
      ))}
    </View>
  )
}
