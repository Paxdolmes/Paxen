import { HStack, Image, Spacer, Text, VStack } from '@expo/ui/swift-ui'
import { font, foregroundStyle, lineLimit, monospacedDigit, padding } from '@expo/ui/swift-ui/modifiers'
import { createLiveActivity, type LiveActivityEnvironment } from 'expo-widgets'

/** What the trip on the lock screen draws. The server sends the same shape (backend paxen/activity.py). */
export type TripActivityProps = {
  status: string // 'active', or how the trip ended
  summary: string // "District"
  eta: number | null // arrival, epoch ms
  headline: string // "Wait for the District at Fulham Broadway"
  next: string | null // "District from Fulham Broadway"
  nextAt: number | null // when that train leaves, epoch ms
  note: string | null // a disruption on the route
}

// Everything this function uses must be declared inside it: it runs on its own in the widget extension.
const TripActivity = (props: TripActivityProps, environment: LiveActivityEnvironment) => {
  'widget'
  const dark = environment.colorScheme === 'dark'
  const brand = dark ? '#5FBCC5' : '#0E5A63'
  const secondary = dark ? '#AEB4BA' : '#54595F'
  const attention = dark ? '#FF8A5B' : '#C2410C'
  const eta = props.status === 'active' && props.eta != null ? new Date(props.eta) : null
  const nextAt = props.nextAt != null ? new Date(props.nextAt) : null
  const time = (size: number) =>
    eta ? (
      <Text date={eta} dateStyle="time" modifiers={[font({ weight: 'bold', size }), monospacedDigit()]} />
    ) : (
      <Text modifiers={[font({ weight: 'bold', size })]}>Done</Text>
    )
  const nextLine = props.next ? (
    <HStack spacing={4}>
      <Text modifiers={[font({ size: 13 }), foregroundStyle(secondary), lineLimit(1)]}>{props.next}</Text>
      {nextAt ? <Text date={nextAt} dateStyle="time" modifiers={[font({ size: 13, weight: 'semibold' }), monospacedDigit()]} /> : null}
    </HStack>
  ) : null

  return {
    banner: (
      <VStack alignment="leading" spacing={6} modifiers={[padding({ all: 16 })]}>
        <HStack spacing={6}>
          <Image systemName="tram.fill" size={12} color={brand} />
          <Text modifiers={[font({ size: 12, weight: 'bold' }), foregroundStyle(brand), lineLimit(1)]}>PAXEN · {props.summary}</Text>
          <Spacer />
          <Text modifiers={[font({ size: 12 }), foregroundStyle(secondary)]}>{eta ? 'Arrive about' : ''}</Text>
        </HStack>
        <HStack spacing={12}>
          <VStack alignment="leading" spacing={2}>
            <Text modifiers={[font({ size: 16, weight: 'semibold' }), lineLimit(2)]}>{props.headline}</Text>
            {nextLine}
          </VStack>
          <Spacer />
          {time(28)}
        </HStack>
        {props.note ? <Text modifiers={[font({ size: 12 }), foregroundStyle(attention), lineLimit(1)]}>{props.note}</Text> : null}
      </VStack>
    ),
    compactLeading: <Image systemName="tram.fill" size={14} color={brand} />,
    compactTrailing: time(14),
    minimal: <Image systemName="tram.fill" size={12} color={brand} />,
    expandedLeading: (
      <VStack alignment="leading" spacing={2} modifiers={[padding({ leading: 8 })]}>
        <Image systemName="tram.fill" size={18} color={brand} />
        <Text modifiers={[font({ size: 12 }), foregroundStyle(secondary), lineLimit(1)]}>{props.summary}</Text>
      </VStack>
    ),
    expandedTrailing: (
      <VStack alignment="trailing" spacing={0} modifiers={[padding({ trailing: 8 })]}>
        <Text modifiers={[font({ size: 11 }), foregroundStyle(secondary)]}>{eta ? 'Arrive' : ''}</Text>
        {time(22)}
      </VStack>
    ),
    expandedBottom: (
      <VStack alignment="leading" spacing={2} modifiers={[padding({ horizontal: 8, bottom: 8 })]}>
        <Text modifiers={[font({ size: 15, weight: 'semibold' }), lineLimit(2)]}>{props.headline}</Text>
        {nextLine}
        {props.note ? <Text modifiers={[font({ size: 12 }), foregroundStyle(attention), lineLimit(1)]}>{props.note}</Text> : null}
      </VStack>
    ),
  }
}

export default createLiveActivity('PaxenTrip', TripActivity)
