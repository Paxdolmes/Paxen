import { FlaskConical, Radio } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Chip } from './primitives/chip'

/** Text wordmark: Roman serif capitals, widely tracked, with a short crimson rule beneath. */
export function Wordmark({ className, size = 22 }: { className?: string; size?: number }) {
  return (
    <span className={cn('inline-flex flex-col items-start text-px-text', className)} style={{ gap: size * 0.16 }}>
      <span
        className="font-serif uppercase"
        style={{ fontSize: size, lineHeight: 1, fontWeight: 700, letterSpacing: '0.16em', marginRight: '-0.16em' }}
      >
        paxen
      </span>
      <span
        aria-hidden
        className="inline-block rounded-full bg-px-accent"
        style={{ width: size * 1.1, height: Math.max(2, Math.round(size * 0.09)) }}
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
