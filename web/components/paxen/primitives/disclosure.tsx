'use client'

import { useId, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Text } from './text'

/** A quiet "show more" row that reveals secondary detail. 44px tall, keyboard and screen-reader friendly. */
export function Disclosure({
  label,
  openLabel,
  defaultOpen = false,
  children,
  className,
}: {
  label: string
  /** Optional label while open, e.g. "Hide details". */
  openLabel?: string
  defaultOpen?: boolean
  children: ReactNode
  className?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  const panelId = useId()
  return (
    <div className={cn('flex flex-col', className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="-mx-2 flex min-h-11 items-center justify-between gap-3 rounded-px-sm px-2 text-left text-px-accent hover:bg-px-surface-sunken"
      >
        <Text variant="callout" as="span" tone="inherit" style={{ fontWeight: 600 }}>
          {open && openLabel ? openLabel : label}
        </Text>
        <ChevronDown className={cn('size-5 shrink-0 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <div id={panelId} className="flex flex-col gap-4 pt-3">
          {children}
        </div>
      )}
    </div>
  )
}
