import { View } from 'react-native'
import type { LiveTrip } from '@/shared/types'
import { usePalette } from '@/lib/theme'
import { Text } from './text'

/** Web preview only (used for screenshots in CI): the iPhone app shows Apple Maps here. */
export default function TripMap(_: { trip: LiveTrip; position: [number, number] | null; follow: boolean }) {
  const p = usePalette()
  return (
    <View style={{ flex: 1, backgroundColor: p.surfaceSunken, alignItems: 'center', justifyContent: 'center' }}>
      <Text variant="footnote" tone="secondary">
        Map (shown on iPhone)
      </Text>
    </View>
  )
}
