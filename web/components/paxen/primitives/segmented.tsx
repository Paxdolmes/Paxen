'use client'

import { useRef } from 'react'
import { cn } from '@/lib/utils'
import { textStyle } from './text'

interface SegmentedProps<T extends string> {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
  scroll?: boolean
  className?: string
}

export function Segmented<T extends string>({ label, value, options, onChange, scroll, className }: SegmentedProps<T>) {
  const ref = useRef<HTMLDivElement>(null)

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const i = options.findIndex((o) => o.value === value)
    const next = options[(i + (e.key === 'ArrowRight' ? 1 : -1) + options.length) % options.length]
    onChange(next.value)
    ref.current?.querySelector<HTMLButtonElement>(`[data-value="${next.value}"]`)?.focus()
  }

  return (
    <div
      ref={ref}
      role="radiogroup"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cn(
        'flex gap-1 rounded-px-md bg-px-surface-sunken p-1',
        scroll ? '-mx-5 overflow-x-auto px-5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden bg-transparent' : '',
        className,
      )}
    >
      {options.map((o) => {
        const selected = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            data-value={o.value}
            onClick={() => onChange(o.value)}
            className={cn(
              'h-10 shrink-0 whitespace-nowrap rounded-px-sm px-3 transition-colors',
              scroll ? 'rounded-full border px-4' : 'flex-1',
              selected
                ? scroll
                  ? 'border-px-brand bg-px-brand text-px-on-brand'
                  : 'bg-px-surface text-px-text shadow-px-card'
                : scroll
                  ? 'border-px-border-strong bg-px-surface text-px-text-secondary'
                  : 'text-px-text-secondary hover:text-px-text',
            )}
            style={{ ...textStyle('subhead'), fontWeight: 600 }}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
