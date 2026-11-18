import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Pressable, Text, View, useColorScheme } from 'react-native'
import { palettes } from '@/shared/paxen-tokens'
import { reportError } from '@/lib/errors'

// Without these, an error while drawing a screen closes the app (React Native treats it as fatal). With them the
// part that failed is replaced by a short note, the rest keeps working, and the error is reported (lib/errors.ts).
// Plain React Native only, so the fallback itself can't fail for want of a theme, font or provider.

type Props = {
  children: ReactNode
  /** 'card': one part of a screen (a small note in its place). 'screen': the whole screen, with Try again.
   *  'silent': something that draws nothing anyway (it just stops). */
  level?: 'card' | 'screen' | 'silent'
  /** Shown on the note, e.g. "This card". */
  label?: string
  /** Called by Try again, after the boundary resets (e.g. to reload data). */
  onRetry?: () => void
}

export class Boundary extends Component<Props, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error : new Error(String(error)) }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    reportError(error, this.props.level === 'screen' ? 'screen' : 'card', info?.componentStack ?? null)
  }

  retry = () => {
    this.setState({ error: null })
    this.props.onRetry?.()
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    if (this.props.level === 'silent') return null
    return this.props.level === 'card' ? (
      <CardNote label={this.props.label ?? 'This part'} onRetry={this.retry} />
    ) : (
      <ScreenNote error={error} onRetry={this.retry} />
    )
  }
}

function CardNote({ label, onRetry }: { label: string; onRetry: () => void }) {
  const p = palettes[useColorScheme() === 'dark' ? 'dark' : 'light']
  return (
    <View style={{ backgroundColor: p.surface, borderRadius: 16, padding: 16, gap: 8 }} accessibilityRole="alert">
      <Text style={{ color: p.textSecondary, fontSize: 15 }}>{label} couldn&apos;t be shown just now.</Text>
      <Pressable accessibilityRole="button" onPress={onRetry} hitSlop={8}>
        <Text style={{ color: p.brand, fontSize: 15, fontWeight: '600' }}>Try again</Text>
      </Pressable>
    </View>
  )
}

export function ScreenNote({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const p = palettes[useColorScheme() === 'dark' ? 'dark' : 'light']
  return (
    <View style={{ flex: 1, backgroundColor: p.canvas, justifyContent: 'center', padding: 32, gap: 16 }} accessibilityRole="alert">
      <Text style={{ color: p.text, fontSize: 22, fontWeight: '700' }}>Something went wrong</Text>
      <Text style={{ color: p.textSecondary, fontSize: 16, lineHeight: 22 }}>
        Paxen hit a problem showing this screen. It has been reported, so it can be fixed. Your commutes and settings
        are safe.
      </Text>
      <Pressable
        accessibilityRole="button"
        onPress={onRetry}
        style={({ pressed }) => ({
          alignSelf: 'flex-start',
          backgroundColor: p.brand,
          borderRadius: 999,
          paddingHorizontal: 24,
          paddingVertical: 12,
          opacity: pressed ? 0.85 : 1,
        })}
      >
        <Text style={{ color: p.onBrand, fontSize: 16, fontWeight: '700' }}>Try again</Text>
      </Pressable>
      <Text style={{ color: p.textSecondary, fontSize: 12 }} selectable numberOfLines={4}>
        {error.name}: {error.message}
      </Text>
    </View>
  )
}
