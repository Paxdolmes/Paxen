import { FlaskConical, Radio } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Chip } from './primitives/chip'

/** Text wordmark: Roman capitals (Cinzel, as on the crest behind the name) and a crest-red dot. */
export function Wordmark({ className, size = 22 }: { className?: string; size?: number }) {
  return (
    <span
      className={cn('inline-flex items-baseline font-serif text-px-brand', className)}
      style={{ fontSize: size, lineHeight: 1, fontWeight: 700, letterSpacing: '0.06em' }}
    >
      PAXEN
      <span
        aria-hidden
        className="ml-[0.1em] inline-block rounded-full bg-px-crest"
        style={{ width: size * 0.22, height: size * 0.22 }}
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
