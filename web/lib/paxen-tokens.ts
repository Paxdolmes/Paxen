/**
 * Paxen design tokens — single source of truth.
 *
 * Web: `paxenCssVariables()` is injected into <head> by app/layout.tsx and
 * Tailwind utilities (`bg-px-surface`, `text-px-brand`, …) map onto the
 * resulting CSS variables in app/globals.css.
 * React Native: import `palettes`, `radii`, `space`, `type` and `shadows.*.rn`
 * directly — every value here is a plain number or hex string.
 */

export type ColorScheme = 'light' | 'dark'

export interface Palette {
  canvas: string
  surface: string
  surfaceRaised: string
  surfaceSunken: string
  border: string
  borderStrong: string
  text: string
  textSecondary: string
  textTertiary: string
  textInverse: string
  brand: string
  brandPressed: string
  onBrand: string
  brandSoft: string
  onBrandSoft: string
  accent: string
  accentPressed: string
  onAccent: string
  accentSoft: string
  onAccentSoft: string
  success: string
  successSoft: string
  onSuccessSoft: string
  watch: string
  watchSoft: string
  onWatchSoft: string
  attention: string
  attentionStrong: string
  onAttention: string
  attentionSoft: string
  onAttentionSoft: string
  focus: string
  overlay: string
}

/*
 * "Silver, ink and a crimson pale".
 * brand = the primary-action colour (ink in light, bright silver in dark).
 * accent = crimson, used sparingly: wordmark rule, active tab, focus, selection, links, "Recommended", the pale.
 * attention is a burnt orange (not red) so "disrupted" never reads as brand.
 * Every text/background pair is WCAG AA; borderStrong is ≥3:1 on all surfaces (UI boundaries).
 */
const light: Palette = {
  canvas: '#ECEDEF',
  surface: '#FFFFFF',
  surfaceRaised: '#FFFFFF',
  surfaceSunken: '#E1E3E6',
  border: '#D3D6DA',
  borderStrong: '#7A8088',
  text: '#111214',
  textSecondary: '#4A4F56',
  textTertiary: '#5C626A',
  textInverse: '#F4F5F6',
  brand: '#16181B',
  brandPressed: '#2C3036',
  onBrand: '#FFFFFF',
  brandSoft: '#E1E3E6',
  onBrandSoft: '#1D2024',
  accent: '#B3262C',
  accentPressed: '#A72226',
  onAccent: '#FFFFFF',
  accentSoft: '#F6E3E4',
  onAccentSoft: '#8C1C21',
  success: '#176E3F',
  successSoft: '#DCEFE3',
  onSuccessSoft: '#135835',
  watch: '#8A5900',
  watchSoft: '#F8EDD2',
  onWatchSoft: '#674200',
  attention: '#A84307',
  attentionStrong: '#8F390A',
  onAttention: '#FFFFFF',
  attentionSoft: '#FBE6D6',
  onAttentionSoft: '#863306',
  focus: '#B3262C',
  overlay: 'rgba(17, 18, 20, 0.45)',
}

const dark: Palette = {
  canvas: '#0E0F11',
  surface: '#181A1D',
  surfaceRaised: '#22252A',
  surfaceSunken: '#22252A',
  border: '#2C3036',
  borderStrong: '#6E757D',
  text: '#ECEDEF',
  textSecondary: '#B4B9BF',
  textTertiary: '#979DA4',
  textInverse: '#111214',
  brand: '#D9DCE0',
  brandPressed: '#C1C5CB',
  onBrand: '#111214',
  brandSoft: '#2A2E34',
  onBrandSoft: '#DCDFE3',
  accent: '#F2737A',
  accentPressed: '#EC5F66',
  onAccent: '#0E0F11',
  accentSoft: '#3A1B1E',
  onAccentSoft: '#FFB8BB',
  success: '#4FC98C',
  successSoft: '#11301F',
  onSuccessSoft: '#93E3B9',
  watch: '#EFC04F',
  watchSoft: '#352B0F',
  onWatchSoft: '#F6D78E',
  attention: '#FF8F3F',
  attentionStrong: '#FF7A1F',
  onAttention: '#1F0D02',
  attentionSoft: '#3A200C',
  onAttentionSoft: '#FFC59A',
  focus: '#F2737A',
  overlay: 'rgba(0, 0, 0, 0.6)',
}

export const palettes: Record<ColorScheme, Palette> = { light, dark }

/** Line chips: muted, distinct fills per mode. Same in both schemes (white text, ≥4.5:1). */
export const modeColors: Record<string, { bg: string; fg: string; label: string }> = {
  tube: { bg: '#2F3E5C', fg: '#FFFFFF', label: 'Underground' },
  overground: { bg: '#8A553F', fg: '#FFFFFF', label: 'Overground' },
  'elizabeth-line': { bg: '#56488A', fg: '#FFFFFF', label: 'Elizabeth line' },
  'national-rail': { bg: '#4A4F57', fg: '#FFFFFF', label: 'National Rail' },
  bus: { bg: '#A8372D', fg: '#FFFFFF', label: 'Buses' },
  dlr: { bg: '#1E6E6E', fg: '#FFFFFF', label: 'DLR' },
  walking: { bg: 'transparent', fg: 'currentColor', label: 'Walking' },
}

export const radii = {
  xs: 6,
  sm: 10,
  md: 14,
  lg: 20,
  xl: 28,
  pill: 999,
} as const

/** 4pt grid. `space[5]` = 20 = the standard screen gutter. */
export const space = {
  0: 0,
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  8: 32,
  10: 40,
  12: 48,
  14: 56,
} as const

export const layout = {
  gutter: space[5],
  maxWidth: 430,
  buttonHeight: { lg: 56, md: 44, sm: 36 },
  tabBarHeight: 64,
  headerHeight: 56,
} as const

export type TypeVariant =
  | 'display'
  | 'title1'
  | 'title2'
  | 'headline'
  | 'body'
  | 'bodyStrong'
  | 'callout'
  | 'subhead'
  | 'footnote'
  | 'caption'

export interface TypeStyle {
  fontSize: number
  lineHeight: number
  fontWeight: 400 | 500 | 600 | 700
  letterSpacing: number
}

export const type: Record<TypeVariant, TypeStyle> = {
  display: { fontSize: 40, lineHeight: 44, fontWeight: 700, letterSpacing: -1.2 },
  title1: { fontSize: 26, lineHeight: 32, fontWeight: 700, letterSpacing: -0.6 },
  title2: { fontSize: 21, lineHeight: 27, fontWeight: 600, letterSpacing: -0.3 },
  headline: { fontSize: 17, lineHeight: 23, fontWeight: 600, letterSpacing: -0.2 },
  body: { fontSize: 16, lineHeight: 24, fontWeight: 400, letterSpacing: -0.1 },
  bodyStrong: { fontSize: 16, lineHeight: 24, fontWeight: 600, letterSpacing: -0.1 },
  callout: { fontSize: 15, lineHeight: 22, fontWeight: 500, letterSpacing: -0.1 },
  subhead: { fontSize: 14, lineHeight: 20, fontWeight: 400, letterSpacing: 0 },
  footnote: { fontSize: 14, lineHeight: 20, fontWeight: 400, letterSpacing: 0 },
  caption: { fontSize: 13, lineHeight: 17, fontWeight: 500, letterSpacing: 0.1 },
}

export interface ShadowToken {
  css: string
  rn: {
    shadowColor: string
    shadowOpacity: number
    shadowRadius: number
    shadowOffset: { width: number; height: number }
    elevation: number
  }
}

export const shadows: Record<ColorScheme, Record<'card' | 'raised' | 'bar', ShadowToken>> = {
  light: {
    card: {
      css: '0 1px 2px rgba(17, 18, 20, 0.04), 0 6px 20px rgba(17, 18, 20, 0.05)',
      rn: { shadowColor: '#111214', shadowOpacity: 0.06, shadowRadius: 12, shadowOffset: { width: 0, height: 4 }, elevation: 2 },
    },
    raised: {
      css: '0 2px 6px rgba(17, 18, 20, 0.06), 0 16px 40px rgba(17, 18, 20, 0.12)',
      rn: { shadowColor: '#111214', shadowOpacity: 0.12, shadowRadius: 24, shadowOffset: { width: 0, height: 10 }, elevation: 8 },
    },
    bar: {
      css: '0 -1px 0 rgba(17, 18, 20, 0.06)',
      rn: { shadowColor: '#111214', shadowOpacity: 0.06, shadowRadius: 0, shadowOffset: { width: 0, height: -1 }, elevation: 0 },
    },
  },
  dark: {
    card: {
      css: '0 0 0 1px rgba(255, 255, 255, 0.04)',
      rn: { shadowColor: '#000000', shadowOpacity: 0, shadowRadius: 0, shadowOffset: { width: 0, height: 0 }, elevation: 0 },
    },
    raised: {
      css: '0 0 0 1px rgba(255, 255, 255, 0.06), 0 16px 40px rgba(0, 0, 0, 0.5)',
      rn: { shadowColor: '#000000', shadowOpacity: 0.5, shadowRadius: 24, shadowOffset: { width: 0, height: 10 }, elevation: 8 },
    },
    bar: {
      css: '0 -1px 0 rgba(255, 255, 255, 0.06)',
      rn: { shadowColor: '#000000', shadowOpacity: 0, shadowRadius: 0, shadowOffset: { width: 0, height: -1 }, elevation: 0 },
    },
  },
}

const kebab = (s: string) => s.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`)

function schemeVars(scheme: ColorScheme) {
  const colors = Object.entries(palettes[scheme]).map(([k, v]) => `--px-${kebab(k)}:${v};`)
  const shade = Object.entries(shadows[scheme]).map(([k, v]) => `--px-shadow-${k}:${v.css};`)
  return [...colors, ...shade].join('')
}

/** Serialises the tokens into CSS custom properties (light + prefers-color-scheme dark). */
export function paxenCssVariables() {
  const fixed = [
    ...Object.entries(radii).map(([k, v]) => `--px-radius-${k}:${v}px;`),
    ...Object.entries(modeColors).map(([k, v]) => `--px-mode-${k}-bg:${v.bg};--px-mode-${k}-fg:${v.fg};`),
    `--px-gutter:${layout.gutter}px;`,
    `--px-max-width:${layout.maxWidth}px;`,
  ].join('')
  return `:root{color-scheme:light;${fixed}${schemeVars('light')}}@media (prefers-color-scheme: dark){:root{color-scheme:dark;${schemeVars('dark')}}}`
}

export const tokens = { palettes, modeColors, radii, space, layout, type, shadows }
