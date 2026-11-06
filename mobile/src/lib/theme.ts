import { useColorScheme } from 'react-native'
import { palettes, shadows, type Palette } from '@/shared/paxen-tokens'

export type { Palette }

export function useScheme() {
  return useColorScheme() === 'dark' ? 'dark' : 'light'
}

/** The current light or dark palette (the same tokens the web app uses). */
export function usePalette(): Palette {
  return palettes[useScheme()]
}

export function useShadow(kind: 'card' | 'raised' | 'bar' = 'card') {
  return shadows[useScheme()][kind].rn
}

/** "#0E5A63" + 0.35 -> "rgba(14, 90, 99, 0.35)" */
export function alpha(hex: string, a: number) {
  const h = hex.replace('#', '')
  const n = parseInt(h.length === 3 ? h.replace(/./g, (c) => c + c) : h, 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}
