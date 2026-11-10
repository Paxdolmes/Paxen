'use client'

import { Activity, Bell, Route, Sun, UserRound, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { textStyle } from './primitives/text'
import type { Tab } from './use-nav'

const items: { tab: Tab; label: string; icon: LucideIcon }[] = [
  { tab: 'today', label: 'Today', icon: Sun },
  { tab: 'routes', label: 'Routes', icon: Route },
  { tab: 'network', label: 'Network', icon: Activity },
  { tab: 'alerts', label: 'Alerts', icon: Bell },
  { tab: 'you', label: 'You', icon: UserRound },
]

export function TabBar({ active, unread, onSelect }: { active: Tab; unread: number; onSelect: (t: Tab) => void }) {
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-30 mx-auto w-full max-w-[430px] bg-px-surface/95 pb-safe shadow-px-bar backdrop-blur-md"
    >
      <ul className="flex h-16 items-stretch">
        {items.map(({ tab, label, icon: Icon }) => {
          const selected = tab === active
          const badge = tab === 'alerts' && unread > 0
          return (
            <li key={tab} className="flex flex-1">
              <button
                type="button"
                onClick={() => onSelect(tab)}
                aria-current={selected ? 'page' : undefined}
                className={cn(
                  'flex flex-1 flex-col items-center justify-center gap-1 transition-colors',
                  selected ? 'text-px-accent' : 'text-px-text-tertiary hover:text-px-text-secondary',
                )}
                style={{ ...textStyle('caption'), fontWeight: selected ? 700 : 500 }}
              >
                <span className="relative">
                  <Icon className="size-6" strokeWidth={selected ? 2.25 : 1.75} aria-hidden />
                  {badge && (
                    <span
                      className="absolute -right-2 -top-1.5 flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-px-attention px-1 text-px-on-attention tabular"
                      style={{ fontSize: 11, fontWeight: 700, lineHeight: 1 }}
                    >
                      {unread > 9 ? '9+' : unread}
                    </span>
                  )}
                </span>
                {label}
                {badge && <span className="sr-only">{`, ${unread} unread`}</span>}
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
