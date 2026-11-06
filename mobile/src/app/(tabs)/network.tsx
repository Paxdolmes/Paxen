import { useState } from 'react'
import { Pressable, View } from 'react-native'
import { AlertTriangle, ChevronDown, RefreshCw } from 'lucide-react-native'
import { fmtAgoSeconds } from '@/shared/format'
import type { LineStatus } from '@/shared/types'
import { useNetwork } from '@/lib/hooks'
import { usePalette } from '@/lib/theme'
import { Screen } from '@/components/screen'
import { Text } from '@/components/text'
import { LineChip, LineStatusText, modeLabel, SeverityDot } from '@/components/transit'
import { Button, Card, Divider, ErrorState, Section, Skeleton } from '@/components/ui'

const MODE_ORDER = ['tube', 'elizabeth-line', 'overground', 'dlr', 'national-rail', 'bus']

function LineRow({ line }: { line: LineStatus }) {
  const p = usePalette()
  const [open, setOpen] = useState(false)
  const hasReason = !!line.reason
  const row = (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingHorizontal: 20, paddingVertical: 14 }}>
      <LineChip mode={line.mode} name={line.line_name} />
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexShrink: 1 }}>
        <SeverityDot category={line.category} />
        <LineStatusText category={line.category} description={line.description} />
        {hasReason && <ChevronDown size={16} color={p.textTertiary} style={{ transform: [{ rotate: open ? '180deg' : '0deg' }] }} />}
      </View>
    </View>
  )
  return (
    <View>
      {hasReason ? (
        <Pressable accessibilityRole="button" accessibilityState={{ expanded: open }} onPress={() => setOpen((v) => !v)}>
          {row}
        </Pressable>
      ) : (
        row
      )}
      {open && line.reason ? (
        <Text variant="footnote" tone="secondary" style={{ paddingHorizontal: 20, paddingBottom: 16 }}>
          {line.reason}
        </Text>
      ) : null}
    </View>
  )
}

function LineList({ lines }: { lines: LineStatus[] }) {
  return (
    <Card>
      {lines.map((l, i) => (
        <View key={l.line_id}>
          {i > 0 && <Divider />}
          <LineRow line={l} />
        </View>
      ))}
    </Card>
  )
}

export default function NetworkScreen() {
  const p = usePalette()
  const { data, error, isLoading, mutate, isValidating } = useNetwork()

  if (error && !data)
    return (
      <Screen title="Network">
        <ErrorState error={error} onRetry={() => mutate()} />
      </Screen>
    )
  if (isLoading || !data)
    return (
      <Screen title="Network">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} style={{ height: 160, borderRadius: 20 }} />
        ))}
      </Screen>
    )

  const mine = data.lines.filter((l) => l.on_my_routes)
  const groups = new Map<string, LineStatus[]>()
  for (const l of data.lines) groups.set(l.mode, [...(groups.get(l.mode) ?? []), l])
  const modes = [...groups.keys()].sort((a, b) => (MODE_ORDER.indexOf(a) + 1 || 99) - (MODE_ORDER.indexOf(b) + 1 || 99))
  const { feed } = data

  return (
    <Screen title="Network" onRefresh={() => mutate()}>
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
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, paddingHorizontal: 4 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexShrink: 1 }}>
          {!feed.fresh && <AlertTriangle size={16} color={p.watch} />}
          <Text variant="footnote" tone={feed.fresh ? 'tertiary' : 'watch'}>
            {feed.age_s != null ? `Updated ${fmtAgoSeconds(feed.age_s)}` : 'Waiting for first update'}
            {!feed.fresh && ' · data may be out of date'}
          </Text>
        </View>
        <Button variant="ghost" size="sm" onPress={() => mutate()} loading={isValidating} icon={(c) => <RefreshCw size={16} color={c} />}>
          Refresh
        </Button>
      </View>
    </Screen>
  )
}
