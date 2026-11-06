import { useState, type ReactNode } from 'react'
import { RefreshControl, ScrollView, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { Radio } from 'lucide-react-native'
import { layout } from '@/shared/paxen-tokens'
import { useDashboard } from '@/lib/hooks'
import { usePalette } from '@/lib/theme'
import { Text } from './text'
import { Wordmark } from './transit'
import { Chip } from './ui'

/** A tab's page: the Paxen header, then scrolling content with pull-to-refresh. */
export function Screen({ title, children, onRefresh, gap = 24 }: { title?: string; children: ReactNode; onRefresh?: () => Promise<unknown>; gap?: number }) {
  const p = usePalette()
  const insets = useSafeAreaInsets()
  const { data: dashboard } = useDashboard()
  const [refreshing, setRefreshing] = useState(false)
  const refresh = onRefresh
    ? async () => {
        setRefreshing(true)
        try {
          await onRefresh()
        } finally {
          setRefreshing(false)
        }
      }
    : undefined
  return (
    <View style={{ flex: 1, backgroundColor: p.canvas }}>
      <View style={{ paddingTop: insets.top, backgroundColor: p.canvas }}>
        <View style={{ height: layout.headerHeight, paddingHorizontal: layout.gutter, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Wordmark />
          {dashboard?.simulated && (
            <View style={{ justifyContent: 'center' }}>
              <Chip tone="brand" icon={(c) => <Radio size={14} color={c} />}>
                Simulated network
              </Chip>
            </View>
          )}
        </View>
      </View>
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingHorizontal: layout.gutter, paddingTop: 8, paddingBottom: 32, gap }}
        refreshControl={refresh ? <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={p.brand} /> : undefined}
      >
        {title && (
          <Text variant="title1" accessibilityRole="header" style={{ paddingHorizontal: 4 }}>
            {title}
          </Text>
        )}
        {children}
      </ScrollView>
    </View>
  )
}
