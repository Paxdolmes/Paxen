import type { ReactNode } from 'react'
import { CloudOff, RotateCw } from 'lucide-react'
import { Button } from './button'
import { Card } from './card'
import { Text } from './text'

export function ErrorState({
  title = 'We couldn’t load this',
  error,
  onRetry,
}: {
  title?: string
  error?: unknown
  onRetry?: () => void
}) {
  const message = error instanceof Error ? error.message : 'Please try again in a moment.'
  return (
    <Card className="flex flex-col items-start gap-3 p-5" role="alert">
      <span className="flex size-10 items-center justify-center rounded-full bg-px-attention-soft text-px-on-attention-soft">
        <CloudOff className="size-5" aria-hidden />
      </span>
      <div className="flex flex-col gap-1">
        <Text variant="headline">{title}</Text>
        <Text variant="subhead" tone="secondary">
          {message}
        </Text>
      </div>
      {onRetry && (
        <Button variant="secondary" size="md" onClick={onRetry} icon={<RotateCw className="size-4" aria-hidden />}>
          Try again
        </Button>
      )}
    </Card>
  )
}

export function EmptyState({ icon, title, body, children }: { icon: ReactNode; title: string; body: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <span className="flex size-14 items-center justify-center rounded-full bg-px-brand-soft text-px-on-brand-soft">{icon}</span>
      <Text variant="title2" className="text-balance">
        {title}
      </Text>
      <Text variant="subhead" tone="secondary" className="max-w-xs text-pretty">
        {body}
      </Text>
      {children}
    </div>
  )
}
