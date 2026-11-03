'use client'

import { useState } from 'react'
import { Gauge } from 'lucide-react'
import { cn } from '@/lib/utils'
import { CONFIDENCE_LABELS } from '@/lib/format'
import type { Confidence } from '@/lib/types'
import { Button } from '../primitives/button'
import { Sheet } from '../primitives/sheet'
import { Text, textStyle } from '../primitives/text'

const toneClass: Record<Confidence, string> = {
  high: 'bg-px-brand-soft text-px-on-brand-soft',
  medium: 'bg-px-watch-soft text-px-on-watch-soft',
  low: 'bg-px-surface-sunken text-px-text-secondary',
}

const meaning: Record<Confidence, string> = {
  high: 'The forecast range is narrow — live arrivals and our model agree.',
  medium: 'Usually right, but the range is moderate. Allow a few minutes either way.',
  low: 'The range is wide. Things could go faster or slower than the middle estimate.',
}

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn('inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2.5', toneClass[confidence])}
        style={{ ...textStyle('caption'), fontWeight: 600 }}
        aria-haspopup="dialog"
      >
        <Gauge className="size-3.5" aria-hidden />
        {CONFIDENCE_LABELS[confidence]} confidence
      </button>
      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title={`${CONFIDENCE_LABELS[confidence]} confidence`}
        footer={
          <Button variant="secondary" block onClick={() => setOpen(false)}>
            Got it
          </Button>
        }
      >
        <Text variant="body" className="text-pretty">
          {meaning[confidence]}
        </Text>
        <Text variant="subhead" tone="secondary" className="text-pretty">
          Based on live arrivals, our correction model and today&apos;s disruption. Low means the range is wide.
        </Text>
      </Sheet>
    </>
  )
}
