import type { CSSProperties, ElementType, ComponentPropsWithoutRef } from 'react'
import { cn } from '@/lib/utils'
import { type TypeVariant, type as typeScale } from '@/lib/paxen-tokens'

export type TextTone =
  | 'primary'
  | 'secondary'
  | 'tertiary'
  | 'brand'
  | 'accent'
  | 'success'
  | 'watch'
  | 'attention'
  | 'onBrand'
  | 'inherit'

const toneClass: Record<TextTone, string> = {
  primary: 'text-px-text',
  secondary: 'text-px-text-secondary',
  tertiary: 'text-px-text-tertiary',
  brand: 'text-px-brand',
  accent: 'text-px-accent',
  success: 'text-px-success',
  watch: 'text-px-watch',
  attention: 'text-px-attention',
  onBrand: 'text-px-on-brand',
  inherit: '',
}

const defaultElement: Record<TypeVariant, ElementType> = {
  display: 'p',
  title1: 'h2',
  title2: 'h2',
  headline: 'h3',
  body: 'p',
  bodyStrong: 'p',
  callout: 'p',
  subhead: 'p',
  footnote: 'p',
  caption: 'span',
}

export function textStyle(variant: TypeVariant): CSSProperties {
  const t = typeScale[variant]
  return {
    fontSize: t.fontSize,
    lineHeight: `${t.lineHeight}px`,
    fontWeight: t.fontWeight,
    letterSpacing: `${t.letterSpacing}px`,
  }
}

type TextProps = {
  variant?: TypeVariant
  tone?: TextTone
  as?: ElementType
  tabular?: boolean
} & ComponentPropsWithoutRef<'p'> &
  Record<string, unknown>

export function Text({
  variant = 'body',
  tone = 'primary',
  as,
  tabular,
  className,
  style,
  ...props
}: TextProps) {
  const Comp = as ?? defaultElement[variant]
  return (
    <Comp
      className={cn(toneClass[tone], tabular && 'tabular', className)}
      style={{ ...textStyle(variant), ...(style as CSSProperties) }}
      {...props}
    />
  )
}
