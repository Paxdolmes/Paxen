import { useEffect, useState, type ReactNode } from 'react'
import {
  ActivityIndicator,
  Animated,
  Pressable,
  ScrollView,
  View,
  type PressableProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native'
import { ChevronDown, CloudOff, RotateCw } from 'lucide-react-native'
import { layout, radii } from '@/shared/paxen-tokens'
import { usePalette, useShadow, type Palette } from '@/lib/theme'
import { Text, textStyle } from './text'

/* ---------- surfaces ---------- */

export function Card({ style, children, ...props }: { style?: StyleProp<ViewStyle>; children?: ReactNode } & Omit<React.ComponentProps<typeof View>, 'style'>) {
  const p = usePalette()
  const shadow = useShadow('card')
  return (
    <View {...props} style={[{ backgroundColor: p.surface, borderRadius: radii.lg }, shadow, style]}>
      {children}
    </View>
  )
}

export function Section({ title, action, children, style }: { title: string; action?: ReactNode; children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[{ gap: 12 }, style]} accessibilityLabel={title}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 4, minHeight: 20 }}>
        <Text variant="footnote" tone="secondary" accessibilityRole="header" style={{ fontWeight: '600', letterSpacing: 0.6, textTransform: 'uppercase' }}>
          {title}
        </Text>
        {action}
      </View>
      {children}
    </View>
  )
}

export function Divider({ style }: { style?: StyleProp<ViewStyle> }) {
  const p = usePalette()
  return <View style={[{ height: 1, width: '100%', backgroundColor: p.border }, style]} />
}

export function Skeleton({ style }: { style?: StyleProp<ViewStyle> }) {
  const p = usePalette()
  const [pulse] = useState(() => new Animated.Value(0.6))
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0.6, duration: 700, useNativeDriver: true }),
      ]),
    )
    loop.start()
    return () => loop.stop()
  }, [pulse])
  return <Animated.View style={[{ backgroundColor: p.surfaceSunken, borderRadius: radii.sm, opacity: pulse }, style]} />
}

/* ---------- buttons ---------- */

type BtnVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger'
type BtnSize = 'lg' | 'md' | 'sm'

const btnColors = (p: Palette, v: BtnVariant) =>
  ({
    primary: { bg: p.brand, pressed: p.brandPressed, fg: p.onBrand, border: undefined },
    secondary: { bg: p.surfaceSunken, pressed: p.border, fg: p.text, border: undefined },
    outline: { bg: p.surface, pressed: p.surfaceSunken, fg: p.text, border: p.borderStrong },
    ghost: { bg: 'transparent', pressed: p.brandSoft, fg: p.brand, border: undefined },
    danger: { bg: p.attentionSoft, pressed: p.attentionSoft, fg: p.onAttentionSoft, border: undefined },
  })[v]

export function Button({
  variant = 'primary',
  size = 'lg',
  block,
  loading,
  disabled,
  icon,
  children,
  style,
  ...props
}: Omit<PressableProps, 'style' | 'children'> & {
  variant?: BtnVariant
  size?: BtnSize
  block?: boolean
  loading?: boolean
  icon?: (color: string) => ReactNode
  children?: ReactNode
  style?: StyleProp<ViewStyle>
}) {
  const p = usePalette()
  const c = btnColors(p, variant)
  const off = disabled || loading
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: !!off, busy: !!loading }}
      disabled={off}
      {...props}
      style={({ pressed }) => [
        {
          height: layout.buttonHeight[size],
          paddingHorizontal: size === 'lg' ? 24 : size === 'md' ? 16 : 12,
          borderRadius: size === 'lg' ? radii.md : radii.sm,
          backgroundColor: pressed ? c.pressed : c.bg,
          borderWidth: c.border ? 1 : 0,
          borderColor: c.border,
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'center',
          gap: size === 'sm' ? 6 : 8,
          opacity: off ? 0.5 : 1,
          alignSelf: block ? 'stretch' : 'flex-start',
          transform: [{ scale: pressed ? 0.98 : 1 }],
        },
        style,
      ]}
    >
      {loading ? <ActivityIndicator color={c.fg} /> : icon?.(c.fg)}
      {typeof children === 'string' ? (
        <Text style={[textStyle(size === 'sm' ? 'subhead' : 'bodyStrong'), { color: c.fg, fontWeight: '600' }]}>{children}</Text>
      ) : (
        children
      )}
    </Pressable>
  )
}

/* ---------- chips ---------- */

export type ChipTone = 'neutral' | 'brand' | 'success' | 'watch' | 'attention' | 'attentionStrong' | 'outline'

export const chipColors = (p: Palette, t: ChipTone) =>
  ({
    neutral: { bg: p.surfaceSunken, fg: p.textSecondary },
    brand: { bg: p.brandSoft, fg: p.onBrandSoft },
    success: { bg: p.successSoft, fg: p.onSuccessSoft },
    watch: { bg: p.watchSoft, fg: p.onWatchSoft },
    attention: { bg: p.attentionSoft, fg: p.onAttentionSoft },
    attentionStrong: { bg: p.attention, fg: p.onAttention },
    outline: { bg: 'transparent', fg: p.textSecondary, border: p.borderStrong },
  })[t] as { bg: string; fg: string; border?: string }

export function Chip({ tone = 'neutral', size = 'sm', icon, children }: { tone?: ChipTone; size?: 'sm' | 'md'; icon?: (color: string) => ReactNode; children: ReactNode }) {
  const p = usePalette()
  const c = chipColors(p, tone)
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        height: size === 'sm' ? 24 : 32,
        paddingHorizontal: size === 'sm' ? 10 : 12,
        borderRadius: radii.pill,
        backgroundColor: c.bg,
        borderWidth: c.border ? 1 : 0,
        borderColor: c.border,
        alignSelf: 'flex-start',
      }}
    >
      {icon?.(c.fg)}
      <Text variant={size === 'sm' ? 'caption' : 'footnote'} color={c.fg} tabular style={{ fontWeight: '600' }} numberOfLines={1}>
        {children}
      </Text>
    </View>
  )
}

/** Toggleable chip (weekday pickers). */
export function ChoiceChip({ selected, onPress, children }: { selected: boolean; onPress: () => void; children: string }) {
  const p = usePalette()
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked: selected }}
      onPress={onPress}
      style={{
        height: 44,
        minWidth: 44,
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: selected ? p.brand : p.surface,
        borderWidth: selected ? 0 : 1,
        borderColor: p.borderStrong,
      }}
    >
      <Text variant="subhead" color={selected ? p.onBrand : p.text} style={{ fontWeight: '600' }}>
        {children}
      </Text>
    </Pressable>
  )
}

/* ---------- segmented ---------- */

export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  scroll,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  scroll?: boolean
}) {
  const p = usePalette()
  const shadow = useShadow('card')
  if (scroll) {
    return (
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        accessibilityRole="radiogroup"
        accessibilityLabel={label}
        style={{ marginHorizontal: -20 }}
        contentContainerStyle={{ gap: 6, paddingHorizontal: 20 }}
      >
        {options.map((o) => {
          const sel = o.value === value
          return (
            <Pressable
              key={o.value}
              accessibilityRole="radio"
              accessibilityState={{ selected: sel }}
              onPress={() => onChange(o.value)}
              style={{
                height: 44,
                paddingHorizontal: 16,
                borderRadius: radii.pill,
                borderWidth: 1,
                borderColor: sel ? p.brand : p.borderStrong,
                backgroundColor: sel ? p.brand : p.surface,
                justifyContent: 'center',
              }}
            >
              <Text variant="subhead" color={sel ? p.onBrand : p.textSecondary} style={{ fontWeight: '600' }}>
                {o.label}
              </Text>
            </Pressable>
          )
        })}
      </ScrollView>
    )
  }
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={label} style={{ flexDirection: 'row', gap: 4, borderRadius: radii.md, backgroundColor: p.surfaceSunken, padding: 4 }}>
      {options.map((o) => {
        const sel = o.value === value
        return (
          <Pressable
            key={o.value}
            accessibilityRole="radio"
            accessibilityState={{ selected: sel }}
            onPress={() => onChange(o.value)}
            style={[
              { flex: 1, height: 44, borderRadius: radii.sm, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 12 },
              sel ? [{ backgroundColor: p.surface }, shadow] : null,
            ]}
          >
            <Text variant="subhead" color={sel ? p.text : p.textSecondary} style={{ fontWeight: '600' }} numberOfLines={1}>
              {o.label}
            </Text>
          </Pressable>
        )
      })}
    </View>
  )
}

/* ---------- disclosure ---------- */

export function Disclosure({ label, openLabel, children, style }: { label: string; openLabel?: string; children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const p = usePalette()
  const [open, setOpen] = useState(false)
  return (
    <View style={style}>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        onPress={() => setOpen((v) => !v)}
        style={{ minHeight: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}
      >
        <Text variant="callout" tone="brand" style={{ fontWeight: '600' }}>
          {open && openLabel ? openLabel : label}
        </Text>
        <ChevronDown size={20} color={p.brand} style={{ transform: [{ rotate: open ? '180deg' : '0deg' }] }} />
      </Pressable>
      {open && <View style={{ gap: 16, paddingTop: 12 }}>{children}</View>}
    </View>
  )
}

/* ---------- states ---------- */

export function ErrorState({ title = 'We couldn’t load this', error, onRetry }: { title?: string; error?: unknown; onRetry?: () => void }) {
  const p = usePalette()
  const message = error instanceof Error ? error.message : 'Please try again in a moment.'
  return (
    <Card style={{ padding: 20, gap: 12, alignItems: 'flex-start' }} accessibilityRole="alert">
      <View style={{ width: 40, height: 40, borderRadius: 20, backgroundColor: p.attentionSoft, alignItems: 'center', justifyContent: 'center' }}>
        <CloudOff size={20} color={p.onAttentionSoft} />
      </View>
      <View style={{ gap: 4 }}>
        <Text variant="headline">{title}</Text>
        <Text variant="subhead" tone="secondary">
          {message}
        </Text>
      </View>
      {onRetry && (
        <Button variant="secondary" size="md" onPress={onRetry} icon={(c) => <RotateCw size={16} color={c} />}>
          Try again
        </Button>
      )}
    </Card>
  )
}

export function EmptyState({ icon, title, body }: { icon: (color: string) => ReactNode; title: string; body: string }) {
  const p = usePalette()
  return (
    <View style={{ alignItems: 'center', gap: 12, paddingHorizontal: 24, paddingVertical: 48 }}>
      <View style={{ width: 56, height: 56, borderRadius: 28, backgroundColor: p.brandSoft, alignItems: 'center', justifyContent: 'center' }}>
        {icon(p.onBrandSoft)}
      </View>
      <Text variant="title2" style={{ textAlign: 'center' }}>
        {title}
      </Text>
      <Text variant="subhead" tone="secondary" style={{ textAlign: 'center', maxWidth: 320 }}>
        {body}
      </Text>
    </View>
  )
}

/** Error text under a form or action. */
export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null
  return (
    <Text variant="footnote" tone="attention" accessibilityRole="alert">
      {children}
    </Text>
  )
}
