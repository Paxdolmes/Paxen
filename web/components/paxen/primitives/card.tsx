import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'
import { Text } from './text'

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-px-lg bg-px-surface shadow-px-card', className)} {...props} />
}

export function Section({
  title,
  action,
  children,
  className,
}: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={cn('flex flex-col gap-3', className)} aria-label={title}>
      <div className="flex items-center justify-between px-1">
        <Text variant="footnote" as="h2" tone="secondary" className="uppercase" style={{ fontWeight: 600, letterSpacing: 0.6 }}>
          {title}
        </Text>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('px-skeleton rounded-px-sm bg-px-surface-sunken', className)} />
}

export function Divider({ className }: { className?: string }) {
  return <div role="separator" className={cn('h-px w-full bg-px-border', className)} />
}
