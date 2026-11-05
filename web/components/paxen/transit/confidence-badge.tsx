'use client'

import { useState } from 'react'
import { Gauge } from 'lucide-react'
import { cn } from '@/lib/utils'
import { CONFIDENCE_PLAIN } from '@/lib/plain'
import type { Confidence } from '@/lib/types'
import { Button } from '../primitives/button'
import { Sheet } from '../primitives/sheet'
import { Text, textStyle } from '../primitives/text'

const toneClass: Record<Confidence, string> = {
  high: 'bg-px-brand-soft text-px-on-brand-soft',
  medium: 'bg-px-watch-soft text-px-on-watch-soft',
  low: 'bg-px-surface-sunken text-px-text-secondary',
}

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const [open, setOpen] = useState(false)
  const { label, meaning } = CONFIDENCE_PLAIN[confidence]
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="-my-2.5 inline-flex min-h-11 shrink-0 items-center"
        aria-haspopup="dialog"
        aria-label={`${label}. Tap to learn what this means.`}
      >
        <span
          className={cn('inline-flex h-7 items-center gap-1 rounded-full px-3', toneClass[confidence])}
          style={{ ...textStyle('caption'), fontWeight: 600 }}
        >
          <Gauge className="size-3.5" aria-hidden />
          {label}
        </span>
      </button>
      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title={label}
        footer={
          <Button variant="secondary" block onClick={() => setOpen(false)}>
            Got it
          </Button>
        }
      >
        <Text variant="body" className="text-pretty">
          {meaning}
        </Text>
        <Text variant="subhead" tone="secondary" className="text-pretty">
          Based on live arrivals, what usually happens on this route, and today&apos;s disruption.
        </Text>
      </Sheet>
    </>
  )
}
