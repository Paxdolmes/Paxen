import { HStack, Spacer, Text, VStack } from '@expo/ui/swift-ui'
import { containerBackground, font, foregroundStyle, lineLimit, monospacedDigit, widgetURL } from '@expo/ui/swift-ui/modifiers'
import { createWidget, type WidgetEnvironment } from 'expo-widgets'

/** The home-screen and lock-screen widget: when to leave for the next commute (built in lib/widget-data.ts). */
export type CommuteWidgetProps = {
  title: string // "To work"
  tone: 'good' | 'slower' | 'disrupted' | 'none'
  statusLabel: string // "All good" | "14 min slower" | "Usual route not running"
  leaveLabel: string // "Leave by" | "Leave"
  leaveAt: number | null // epoch ms; null with leaveText set
  leaveText: string | null // "Now", or "" when nothing is known
  arriveAt: number | null
  route: string // "District"
  stale: boolean // these times have aged: only the usual journey time is shown
  usual: string | null // "Usually 32 min"
}

// Everything this function uses must be declared inside it: it runs on its own in the widget extension.
const CommuteWidget = (props: CommuteWidgetProps, environment: WidgetEnvironment) => {
  'widget'
  const dark = environment.colorScheme === 'dark'
  const full = environment.widgetRenderingMode === 'fullColor' || environment.widgetRenderingMode == null
  const background = dark ? '#1B1E21' : '#FFFFFF'
  const brand = dark ? '#5FBCC5' : '#0E5A63'
  const secondary = dark ? '#AEB4BA' : '#54595F'
  const toneColor = !full
    ? secondary
    : props.tone === 'good'
      ? dark ? '#6BCB8B' : '#1E7A45'
      : props.tone === 'none'
        ? secondary
        : dark ? '#FF8A5B' : '#C2410C'
  const leaveAt = props.leaveAt != null ? new Date(props.leaveAt) : null
  const arriveAt = props.arriveAt != null ? new Date(props.arriveAt) : null
  const family = environment.widgetFamily
  const open = widgetURL('paxen://')
  const bg = containerBackground(background, 'widget')

  const leave = (size: number) =>
    props.stale ? (
      <Text modifiers={[font({ size: size * 0.6, weight: 'semibold' }), lineLimit(2)]}>{props.usual ?? 'Open Paxen'}</Text>
    ) : leaveAt ? (
      <Text date={leaveAt} dateStyle="time" modifiers={[font({ size, weight: 'bold' }), monospacedDigit()]} />
    ) : (
      <Text modifiers={[font({ size, weight: 'bold' })]}>{props.leaveText ?? ''}</Text>
    )

  if (family === 'accessoryInline') {
    return props.stale || !leaveAt ? (
      <Text modifiers={[open, bg]}>{props.title}: {props.stale ? (props.usual ?? 'open Paxen') : props.statusLabel}</Text>
    ) : (
      <HStack spacing={4} modifiers={[open, bg]}>
        <Text>{props.leaveLabel}</Text>
        <Text date={leaveAt} dateStyle="time" />
      </HStack>
    )
  }

  if (family === 'accessoryRectangular') {
    return (
      <VStack alignment="leading" spacing={1} modifiers={[open, bg]}>
        <Text modifiers={[font({ size: 12, weight: 'semibold' }), lineLimit(1)]}>{props.title} · {props.stale ? 'Paxen' : props.statusLabel}</Text>
        <HStack spacing={4}>
          {props.stale ? null : <Text modifiers={[font({ size: 13 })]}>{props.leaveLabel}</Text>}
          {leave(props.stale ? 22 : 15)}
        </HStack>
        <Text modifiers={[font({ size: 12 }), lineLimit(1)]}>{props.route}</Text>
      </VStack>
    )
  }

  const head = (
    <HStack spacing={4}>
      <Text modifiers={[font({ size: 12, weight: 'bold' }), foregroundStyle(brand), lineLimit(1)]}>{props.title.toUpperCase()}</Text>
      <Spacer />
    </HStack>
  )
  const status = (
    <Text modifiers={[font({ size: 12, weight: 'semibold' }), foregroundStyle(toneColor), lineLimit(1)]}>
      {props.stale ? 'Open for live times' : props.statusLabel}
    </Text>
  )

  if (family === 'systemMedium') {
    return (
      <HStack spacing={12} modifiers={[open, bg]}>
        <VStack alignment="leading" spacing={4}>
          {head}
          <Text modifiers={[font({ size: 12 }), foregroundStyle(secondary)]}>{props.stale ? 'Your commute' : props.leaveLabel}</Text>
          {leave(34)}
          <Spacer />
          {status}
        </VStack>
        <VStack alignment="trailing" spacing={4}>
          <Text modifiers={[font({ size: 12 }), foregroundStyle(secondary)]}>{arriveAt && !props.stale ? 'Arrive about' : ''}</Text>
          {arriveAt && !props.stale ? <Text date={arriveAt} dateStyle="time" modifiers={[font({ size: 22, weight: 'semibold' }), monospacedDigit()]} /> : null}
          <Spacer />
          <Text modifiers={[font({ size: 12 }), foregroundStyle(secondary), lineLimit(2)]}>{props.route}</Text>
        </VStack>
      </HStack>
    )
  }

  return (
    <VStack alignment="leading" spacing={3} modifiers={[open, bg]}>
      {head}
      <Text modifiers={[font({ size: 12 }), foregroundStyle(secondary)]}>{props.stale ? 'Your commute' : props.leaveLabel}</Text>
      {leave(30)}
      <Spacer />
      {status}
      <Text modifiers={[font({ size: 11 }), foregroundStyle(secondary), lineLimit(1)]}>{props.route}</Text>
    </VStack>
  )
}

export default createWidget('PaxenCommute', CommuteWidget, {
  title: 'Paxen',
  tone: 'none',
  statusLabel: 'Open Paxen to set up',
  leaveLabel: 'Leave by',
  leaveAt: null,
  leaveText: '',
  arriveAt: null,
  route: '',
  stale: true,
  usual: null,
})
