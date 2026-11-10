import { useState, type ReactNode } from 'react'
import { Pressable, View } from 'react-native'
import { Ban, ChevronDown, Footprints, Pin, Play, Repeat2 } from 'lucide-react-native'
import { fareLabel, fmtMin, fmtTime } from '@/shared/format'
import { crowdingWords, newDelayRiskWords, onTimeWords, waitBasisHint } from '@/shared/plain'
import type { RouteOption } from '@/shared/types'
import { usePalette } from '@/lib/theme'
import { FullnessChip, LIVE_BASIS, TrainsAhead } from './fullness'
import { Text } from './text'
import { ConfidenceBadge, CrowdingChip, DisruptionNote, LineChip, ModeIcon, RangeBar, type TimeAxis } from './transit'
import { Button, Card, Chip, Divider } from './ui'

function vsUsual(min: number | null, isUsual: boolean) {
  if (isUsual || min == null) return null
  const m = Math.round(min)
  // compared with the usual route as it is today (not with a normal day)
  if (m === 0) return { text: 'Same as your usual route today', tone: 'secondary' as const }
  return m < 0
    ? { text: `${Math.abs(m)} min faster than your usual route today`, tone: 'success' as const }
    : { text: `${m} min slower than your usual route today`, tone: 'secondary' as const }
}

function Meta({ icon, children, color }: { icon?: ReactNode; children: ReactNode; color?: string }) {
  const p = usePalette()
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
      {icon}
      <Text tabular color={color ?? p.textSecondary} style={{ fontSize: 14, lineHeight: 20, fontWeight: '500' }}>
        {children}
      </Text>
    </View>
  )
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
  const p = usePalette()
  const [open, setOpen] = useState(false)
  const transit = option.legs.filter((l) => l.mode !== 'walking')
  const vs = vsUsual(option.vs_usual_min, option.is_usual)
  const off = !option.feasible
  const onTime = onTimeWords(option.on_time_chance)
  const riskText = newDelayRiskWords(option.disruption_risk)

  return (
    <Card style={[{ overflow: 'hidden', opacity: off ? 0.7 : 1 }, option.is_recommended ? { borderWidth: 2, borderColor: p.brand } : null]}>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={`${option.summary}, arrive ${fmtTime(option.arrive_at)}, ${fmtMin(option.duration.p50)}`}
        onPress={() => setOpen((v) => !v)}
        style={{ padding: 20, paddingBottom: 12, gap: 12 }}
      >
        <View style={{ flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6, flex: 1 }}>
            {option.is_recommended && <Chip tone="brand">Recommended</Chip>}
            {option.is_usual && <Chip tone="outline">Usual</Chip>}
            {off && (
              <Chip tone="attention" icon={(c) => <Ban size={14} color={c} />}>
                Not running
              </Chip>
            )}
          </View>
          <ChevronDown size={20} color={p.textTertiary} style={{ transform: [{ rotate: open ? '180deg' : '0deg' }] }} />
        </View>

        <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
          {transit.map((l, i) => (
            <LineChip key={`${l.line_id}-${i}`} mode={l.mode} name={l.line_name ?? l.mode} status={l.status} muted={off} />
          ))}
        </View>

        <View style={{ flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12 }}>
          <View>
            <Text variant="caption" tone="secondary">
              Arrive
            </Text>
            <Text variant="title1" tabular style={off ? { textDecorationLine: 'line-through' } : null}>
              {fmtTime(option.arrive_at)}
            </Text>
          </View>
          <View style={{ alignItems: 'flex-end', flexShrink: 1 }}>
            <Text variant="headline" tabular>
              {fmtMin(option.duration.p50)}
            </Text>
            {vs && (
              <Text variant="footnote" tone={vs.tone} tabular style={{ fontWeight: '600', textAlign: 'right' }}>
                {vs.text}
              </Text>
            )}
          </View>
        </View>

        {axis && !off && (
          <View style={{ gap: 4 }}>
            <RangeBar range={option.arrive_range} median={option.arrive_at} axis={axis} tone={option.is_recommended ? 'brand' : option.disruptions.length ? 'attention' : 'muted'} />
            <Text variant="caption" tone="secondary" tabular>
              Likely between {fmtTime(option.arrive_range[0])} and {fmtTime(option.arrive_range[1])}
            </Text>
          </View>
        )}

        <View style={{ flexDirection: 'row', flexWrap: 'wrap', columnGap: 16, rowGap: 4 }}>
          <Meta icon={<Footprints size={14} color={p.textSecondary} />}>{fmtMin(option.walking_min)} walk</Meta>
          <Meta icon={<Repeat2 size={14} color={p.textSecondary} />}>
            {option.changes === 0 ? 'Direct' : `${option.changes} change${option.changes > 1 ? 's' : ''}`}
          </Meta>
          {!off && onTime && <Meta color={p[onTime.tone]}>{onTime.text}</Meta>}
          {option.reliability && <Meta>{option.reliability.label}</Meta>}
          {option.fare && <Meta>{fareLabel(option.fare)}</Meta>}
        </View>
      </Pressable>

      <View style={{ gap: 8, paddingHorizontal: 20, paddingBottom: 16 }}>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
          <ConfidenceBadge confidence={option.confidence} />
          {option.fullness ? <FullnessChip fullness={option.fullness} /> : <CrowdingChip crowding={option.crowding} />}
        </View>
        {option.fullness?.advice && !off ? (
          <Text variant="footnote" style={{ fontWeight: '600' }}>
            {option.fullness.advice}
          </Text>
        ) : null}
        {option.disruptions.map((d) => (
          <DisruptionNote key={d.line_id} disruption={d} />
        ))}
        {riskText && !off && (
          <Text variant="footnote" tone="secondary">
            {riskText}
          </Text>
        )}
      </View>

      {open && (
        <View style={{ gap: 16, paddingHorizontal: 20, paddingBottom: 20 }}>
          <Divider />
          <View style={{ gap: 12 }}>
            {option.legs.map((leg, i) => {
              const basis = waitBasisHint(leg)
              return (
                <View key={`${leg.from}-${i}`} style={{ flexDirection: 'row', gap: 12 }}>
                  <View style={{ width: 28, height: 28, borderRadius: 14, backgroundColor: p.surfaceSunken, alignItems: 'center', justifyContent: 'center', marginTop: 2 }}>
                    <ModeIcon mode={leg.mode} color={p.textSecondary} />
                  </View>
                  <View style={{ flex: 1, gap: 2 }}>
                    {leg.mode === 'walking' ? (
                      <Text variant="callout">
                        Walk {fmtMin(leg.ride_min)} to {leg.to}
                      </Text>
                    ) : (
                      <>
                        <Text variant="callout" style={{ fontWeight: '600' }}>
                          {leg.line_name}
                          {leg.direction ? ` towards ${leg.direction}` : ''}
                        </Text>
                        <Text variant="footnote" tone="secondary">
                          {leg.from} → {leg.to}
                        </Text>
                        <Text variant="footnote" tone="secondary" tabular>
                          Wait {fmtMin(leg.wait_min)} · ride {fmtMin(leg.ride_min)} ·{' '}
                          <Text variant="footnote" tone={basis.live ? 'success' : 'secondary'} style={{ fontWeight: '600' }}>
                            {basis.label}
                          </Text>
                        </Text>
                      </>
                    )}
                  </View>
                </View>
              )
            })}
          </View>
          {option.fullness?.live && option.fullness.trains.length > 0 && (
            <View style={{ gap: 8 }}>
              <Text variant="footnote" tone="secondary" style={{ fontWeight: '600' }}>
                Next trains from {option.fullness.stop}
              </Text>
              <TrainsAhead trains={option.fullness.trains} catchIndex={option.fullness.catch_index} />
            </View>
          )}
          {option.fullness ? (
            <Text variant="caption" tone="secondary">
              {option.fullness.live ? LIVE_BASIS : option.fullness.basis}
            </Text>
          ) : null}
          {option.crowding.basis ? (
            <Text variant="caption" tone="secondary">
              {crowdingWords(option.crowding.basis)}
            </Text>
          ) : null}
          {!off && (
            <View style={{ gap: 8 }}>
              {canStart && (
                <Button block onPress={onStart} loading={starting} icon={(c) => <Play size={16} color={c} fill={c} />}>
                  I&apos;m leaving now
                </Button>
              )}
              {!option.is_usual && (
                <Button variant="secondary" block onPress={onMakeUsual} loading={savingUsual} icon={(c) => <Pin size={16} color={c} />}>
                  Make this my usual route
                </Button>
              )}
            </View>
          )}
        </View>
      )}
    </Card>
  )
}
