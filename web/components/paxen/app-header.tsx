import { FlaskConical, Radio } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Chip } from './primitives/chip'

/** Text wordmark: lowercase, tight, with a "signal" dot that reads as on-time. */
export function Wordmark({ className, size = 22 }: { className?: string; size?: number }) {
  return (
    <span
      className={cn('inline-flex items-baseline text-px-brand', className)}
      style={{ fontSize: size, lineHeight: 1, fontWeight: 800, letterSpacing: '-0.055em' }}
    >
      paxen
      <span
        aria-hidden
        className="ml-[0.08em] inline-block rounded-full bg-px-success"
        style={{ width: size * 0.26, height: size * 0.26 }}
      />
    </span>
  )
}

export function AppHeader({ demo, simulated }: { demo: boolean; simulated: boolean }) {
  return (
    <header className="sticky top-0 z-20 bg-px-canvas/90 pt-safe backdrop-blur-md">
      <div className="flex h-14 items-center justify-between gap-3 px-5">
        <Wordmark />
        <span className="sr-only">Paxen</span>
        <div className="flex items-center gap-1.5">
          {simulated && (
            <Chip tone="brand" icon={<Radio className="size-3.5" aria-hidden />}>
              Simulated network
            </Chip>
          )}
          {demo && (
            <Chip tone="outline" icon={<FlaskConical className="size-3.5" aria-hidden />}>
              Demo data
            </Chip>
          )}
        </div>
      </div>
    </header>
  )
}
