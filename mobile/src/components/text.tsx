import { Text as RNText, type TextProps, type TextStyle } from 'react-native'
import { type as typeScale, type TypeVariant } from '@/shared/paxen-tokens'
import { usePalette, type Palette } from '@/lib/theme'

export type TextTone =
  | 'primary'
  | 'secondary'
  | 'tertiary'
  | 'brand'
  | 'success'
  | 'watch'
  | 'attention'
  | 'onBrand'
  | 'inherit'

export const toneColor = (p: Palette, tone: TextTone): string | undefined =>
  ({
    primary: p.text,
    secondary: p.textSecondary,
    tertiary: p.textTertiary,
    brand: p.brand,
    success: p.success,
    watch: p.watch,
    attention: p.attention,
    onBrand: p.onBrand,
    inherit: undefined,
  })[tone]

export function textStyle(variant: TypeVariant): TextStyle {
  const t = typeScale[variant]
  return {
    fontSize: t.fontSize,
    lineHeight: t.lineHeight,
    fontWeight: String(t.fontWeight) as TextStyle['fontWeight'],
    letterSpacing: t.letterSpacing,
  }
}

export function Text({
  variant = 'body',
  tone = 'primary',
  color,
  tabular,
  weight,
  style,
  ...props
}: TextProps & { variant?: TypeVariant; tone?: TextTone; color?: string; tabular?: boolean; weight?: TextStyle['fontWeight'] }) {
  const p = usePalette()
  const c = color ?? toneColor(p, tone)
  return (
    <RNText
      {...props}
      style={[
        textStyle(variant),
        c ? { color: c } : null,
        tabular ? { fontVariant: ['tabular-nums'] } : null,
        weight ? { fontWeight: weight } : null,
        style,
      ]}
    />
  )
}
