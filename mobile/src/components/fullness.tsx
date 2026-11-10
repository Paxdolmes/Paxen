import { useState } from 'react'
import { View } from 'react-native'
import { Users } from 'lucide-react-native'
import { radii } from '@/shared/paxen-tokens'
import type { BoardingFullness, FullnessLevel, UpcomingTrain } from '@/shared/types'
import { api } from '@/lib/api'
import { usePalette } from '@/lib/theme'
import { Text } from './text'
import { Button, Chip, type ChipTone } from './ui'

// How full the train you'd board is likely to be (backend paxen/fullness.py). Always shown as an estimate.

const tone: Record<FullnessLevel, ChipTone> = { packed: 'attention', standing: 'watch', space: 'success' }
const short: Record<FullnessLevel, string> = { packed: 'Packed', standing: 'Standing', space: 'Space' }

export const LIVE_BASIS = 'Estimate from typical loads, the live gap between trains and how busy stations are now. Not a passenger count.'

export function FullnessChip({ fullness }: { fullness: BoardingFullness }) {
  return (
    <View accessibilityLabel={`Train fullness estimate: ${fullness.label}`}>
      <Chip tone={tone[fullness.level]} icon={(c) => <Users size={14} color={c} />}>
        {fullness.label}
      </Chip>
    </View>
  )
}

/** The next trains at the platform, each with its likely fullness; the one you'd catch is outlined. */
export function TrainsAhead({ trains, catchIndex }: { trains: UpcomingTrain[]; catchIndex: number | null }) {
  const p = usePalette()
  const shown = trains.filter((t) => t.fullness).slice(0, 4)
  if (!shown.length) return null
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
      {shown.map((t) => {
        const f = t.fullness!
        const i = trains.indexOf(t)
        const yours = i === catchIndex
        const c = { packed: [p.attentionSoft, p.onAttentionSoft], standing: [p.watchSoft, p.onWatchSoft], space: [p.successSoft, p.onSuccessSoft] }[f.level]
        return (
          <View
            key={t.at}
            accessibilityLabel={`${t.at_local} train: ${f.label}${f.gap_min ? `, ${Math.round(f.gap_min)} minutes behind the train ahead` : ''}${yours ? '. The one you would catch' : ''}`}
            style={{ minWidth: 72, gap: 2, paddingVertical: 8, paddingHorizontal: 10, borderRadius: radii.md, backgroundColor: c[0], borderWidth: 2, borderColor: yours ? c[1] : 'transparent' }}
          >
            <Text variant="callout" color={c[1]} tabular style={{ fontWeight: '700' }}>
              {t.at_local}
            </Text>
            <Text variant="caption" color={c[1]} style={{ fontWeight: '600' }}>
              {short[f.level]}
            </Text>
          </View>
        )
      })}
    </View>
  )
}

/** Today's hero and the live trip: how full your train is likely to be, and whether to wait for the next one. */
export function FullnessCard({ fullness }: { fullness: BoardingFullness }) {
  const p = usePalette()
  const where = `${fullness.line_name ?? 'Your train'} at ${fullness.stop}`
  if (!fullness.live) {
    return (
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
        <FullnessChip fullness={fullness} />
        <Text variant="footnote" tone="secondary" style={{ flexShrink: 1 }}>
          {where} at this time
        </Text>
      </View>
    )
  }
  return (
    <View style={{ gap: 10, borderRadius: radii.md, borderWidth: 1, borderColor: p.border, padding: 14 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <Text variant="subhead" style={{ fontWeight: '600', flexShrink: 1 }} numberOfLines={2}>
          {where}
        </Text>
        <FullnessChip fullness={fullness} />
      </View>
      <TrainsAhead trains={fullness.trains} catchIndex={fullness.catch_index} />
      {fullness.advice ? (
        <Text variant="callout" style={{ fontWeight: '600' }}>
          {fullness.advice}
        </Text>
      ) : null}
      <Text variant="caption" tone="secondary">
        {LIVE_BASIS}
      </Text>
    </View>
  )
}

export interface BoardingSnapshot {
  legIndex: number
  lineId: string
  stopId: string
  train: UpcomingTrain | null
}

/** One tap after boarding. The answer, with what we estimated, is how the estimate gets checked. */
export function BoardingQuestion({ tripId, snap, onDone }: { tripId: string; snap: BoardingSnapshot; onDone: () => void }) {
  const p = usePalette()
  const [state, setState] = useState<'ask' | 'sending' | 'thanks'>('ask')
  const answer = async (gotOn: boolean) => {
    setState('sending')
    const f = snap.train?.fullness
    try {
      await api.boarding({
        trip_id: tripId,
        line_id: snap.lineId,
        stop_id: snap.stopId,
        train_at: snap.train?.at ?? null,
        level: f?.level ?? null,
        share: f?.share ?? null,
        typical_share: f?.typical_share ?? null,
        gap_min: f?.gap_min ?? null,
        got_on: gotOn,
      })
    } catch {
      /* best effort: it's a calibration hint, not something the user needs */
    }
    setState('thanks')
    setTimeout(onDone, 2500)
  }
  if (state === 'thanks') {
    return (
      <Text variant="footnote" tone="secondary" accessibilityLiveRegion="polite">
        Thanks. That helps make the fullness estimates more accurate.
      </Text>
    )
  }
  return (
    <View style={{ gap: 10, borderRadius: radii.md, backgroundColor: p.brandSoft, padding: 14 }}>
      <Text variant="callout" color={p.onBrandSoft} style={{ fontWeight: '600' }}>
        Did you get on the first train{snap.train ? ` (${snap.train.at_local})` : ''}?
      </Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
        <Button size="sm" onPress={() => answer(true)} loading={state === 'sending'}>
          Yes
        </Button>
        <Button size="sm" variant="secondary" onPress={() => answer(false)} disabled={state === 'sending'}>
          No, it was too full
        </Button>
        <Button size="sm" variant="ghost" onPress={onDone} disabled={state === 'sending'}>
          Skip
        </Button>
      </View>
    </View>
  )
}
