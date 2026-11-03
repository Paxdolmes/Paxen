'use client'

import { useCallback } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import type { Preference } from '@/lib/types'

export const TABS = ['today', 'routes', 'network', 'alerts', 'you'] as const
export type Tab = (typeof TABS)[number]

export function useNav() {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const raw = params.get('tab')
  const tab: Tab = (TABS as readonly string[]).includes(raw ?? '') ? (raw as Tab) : 'today'

  const go = useCallback(
    (next: Tab, extra: Record<string, string | null | undefined> = {}, opts: { replace?: boolean } = {}) => {
      const sp = new URLSearchParams(next === tab ? params.toString() : '')
      if (next === 'today') sp.delete('tab')
      else sp.set('tab', next)
      for (const [k, v] of Object.entries(extra)) {
        if (v == null || v === '') sp.delete(k)
        else sp.set(k, v)
      }
      const qs = sp.toString()
      const url = qs ? `${pathname}?${qs}` : pathname
      if (opts.replace) router.replace(url, { scroll: false })
      else router.push(url)
    },
    [params, pathname, router, tab],
  )

  return {
    tab,
    commute: params.get('commute'),
    pref: (params.get('pref') as Preference | null) ?? undefined,
    go,
  }
}
