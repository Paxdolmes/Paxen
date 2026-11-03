import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { textStyle } from './text'

export type ChipTone = 'neutral' | 'brand' | 'success' | 'watch' | 'attention' | 'attentionStrong' | 'outline'

const toneClass: Record<ChipTone, string> = {
  neutral: 'bg-px-surface-sunken text-px-text-secondary',
  brand: 'bg-px-brand-soft text-px-on-brand-soft',
  success: 'bg-px-success-soft text-px-on-success-soft',
  watch: 'bg-px-watch-soft text-px-on-watch-soft',
  attention: 'bg-px-attention-soft text-px-on-attention-soft',
  attentionStrong: 'bg-px-attention text-px-on-attention',
  outline: 'border border-px-border-strong text-px-text-secondary',
}

interface ChipProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: ChipTone
  size?: 'sm' | 'md'
  icon?: ReactNode
}

export function Chip({ tone = 'neutral', size = 'sm', icon, className, children, style, ...props }: ChipProps) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full',
        size === 'sm' ? 'h-6 px-2.5' : 'h-8 px-3',
        toneClass[tone],
        className,
      )}
      style={{ ...textStyle(size === 'sm' ? 'caption' : 'footnote'), fontWeight: 600, ...style }}
      {...props}
    >
      {icon}
      {children}
    </span>
  )
}

interface ChoiceChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected: boolean
}

/** Toggleable chip (weekday pickers, filters). */
export function ChoiceChip({ selected, className, children, style, ...props }: ChoiceChipProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cn(
        'inline-flex h-11 min-w-11 shrink-0 items-center justify-center rounded-full px-4 transition-colors',
        selected
          ? 'bg-px-brand text-px-on-brand'
          : 'border border-px-border-strong bg-px-surface text-px-text hover:bg-px-surface-sunken',
        className,
      )}
      style={{ ...textStyle('subhead'), fontWeight: 600, ...style }}
      {...props}
    >
      {children}
    </button>
  )
}
