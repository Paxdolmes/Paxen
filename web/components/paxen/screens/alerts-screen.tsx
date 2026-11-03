'use client'

import { useEffect, useRef, useState } from 'react'
import { BellOff, ThumbsDown, ThumbsUp, Target } from 'lucide-react'
import { mutate as globalMutate } from 'swr'
import { api } from '@/lib/api'
import { CONFIDENCE_LABELS, fmtAgo } from '@/lib/format'
import { useAlerts } from '@/lib/hooks'
import type { Alert } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Card, Skeleton } from '../primitives/card'
import { EmptyState, ErrorState } from '../primitives/states'
import { Text } from '../primitives/text'

type Feedback = NonNullable<Alert['feedback']>

const FEEDBACK: { value: Feedback; label: string; icon: typeof ThumbsUp }[] = [
  { value: 'useful', label: 'Useful', icon: ThumbsUp },
  { value: 'not_useful', label: 'Not useful', icon: ThumbsDown },
  { value: 'inaccurate', label: 'Inaccurate', icon: Target },
]

function AlertCard({ alert, onFeedback }: { alert: Alert; onFeedback: (f: Feedback) => Promise<void> }) {
  const [pending, setPending] = useState<Feedback | null>(null)
  const [failed, setFailed] = useState(false)

  const send = async (f: Feedback) => {
    setPending(f)
    setFailed(false)
    try {
      await onFeedback(f)
    } catch {
      setFailed(true)
    } finally {
      setPending(null)
    }
  }

  return (
    <Card className={cn('flex flex-col gap-3 p-4', !alert.read && 'ring-1 ring-px-attention/40')}>
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <span
            className="flex size-6 items-center justify-center rounded-md bg-px-brand text-px-on-brand"
            style={{ fontSize: 14, fontWeight: 800, letterSpacing: '-0.05em' }}
            aria-hidden
          >
            p
          </span>
          <Text variant="caption" tone="secondary">
            Paxen
          </Text>
        </span>
        <Text variant="caption" tone="tertiary">
          <time dateTime={alert.created_at}>{fmtAgo(alert.created_at)}</time>
        </Text>
      </div>
      <div className="flex flex-col gap-1">
        <Text
          variant="footnote"
          as="h3"
          tone={alert.kind === 'usual_unavailable' ? 'attention' : 'primary'}
          className="uppercase"
          style={{ fontWeight: 700, letterSpacing: 0.5 }}
        >
          {alert.title}
        </Text>
        <Text variant="callout" className="text-pretty">
          {alert.body}
        </Text>
        <Text variant="footnote" tone="secondary">
          Forecast confidence: {CONFIDENCE_LABELS[alert.confidence]}
        </Text>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Was this alert helpful?">
        {FEEDBACK.map(({ value, label, icon: Icon }) => {
          const selected = alert.feedback === value
          return (
            <button
              key={value}
              type="button"
              aria-pressed={selected}
              disabled={pending !== null}
              onClick={() => send(value)}
              className={cn(
                'inline-flex h-9 items-center gap-1.5 rounded-full border px-3 transition-colors disabled:opacity-60',
                selected
                  ? 'border-px-brand bg-px-brand text-px-on-brand'
                  : 'border-px-border-strong bg-px-surface text-px-text hover:bg-px-surface-sunken',
              )}
              style={{ fontSize: 13, fontWeight: 600 }}
            >
              <Icon className="size-3.5" aria-hidden />
              {label}
            </button>
          )
        })}
      </div>
      {failed && (
        <Text variant="footnote" tone="attention" role="alert">
          Couldn&apos;t send feedback. Try again.
        </Text>
      )}
    </Card>
  )
}

export function AlertsScreen() {
  const { data, error, isLoading, mutate } = useAlerts()
  const markedRef = useRef(false)

  useEffect(() => {
    if (markedRef.current || !data?.some((a) => !a.read)) return
    markedRef.current = true
    api
      .markAlertsRead()
      .then(() => globalMutate(['dashboard']))
      .catch(() => {
        markedRef.current = false
      })
  }, [data])

  const feedback = async (id: string, f: Feedback) => {
    await api.alertFeedback(id, f)
    await mutate((list) => list?.map((a) => (a.id === id ? { ...a, feedback: f } : a)), { revalidate: false })
  }

  if (error && !data) return <ErrorState error={error} onRetry={() => mutate()} />

  return (
    <div className="flex flex-col gap-5">
      <Text variant="title1" as="h1" className="px-1">
        Alerts
      </Text>
      {isLoading || !data ? (
        <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading alerts">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-44 w-full rounded-px-lg" />
          ))}
        </div>
      ) : data.length === 0 ? (
        <EmptyState
          icon={<BellOff className="size-6" aria-hidden />}
          title="No alerts — that's a good thing"
          body="Paxen only alerts you when your usual route is materially slower and an alternative is clearly better, or the risk of being late is significant. You can tune this in You → Alerts."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {data.map((a) => (
            <li key={a.id}>
              <AlertCard alert={a} onFeedback={(f) => feedback(a.id, f)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
