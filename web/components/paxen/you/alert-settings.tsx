'use client'

import { useEffect, useRef, useState } from 'react'
import { mutate } from 'swr'
import { api } from '@/lib/api'
import type { Dashboard, User } from '@/lib/types'
import { Card, Divider, Section } from '../primitives/card'
import { SettingRow, Stepper, Switch, TimeField } from '../primitives/controls'
import { Text } from '../primitives/text'

type Patch = Partial<Pick<User, 'monitoring_paused' | 'quiet_start' | 'quiet_end' | 'alert_threshold_min' | 'min_gain_min'>>

export function AlertSettings({ user }: { user: User }) {
  const [local, setLocal] = useState(user)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pending = useRef<Patch>({})

  useEffect(() => setLocal(user), [user])
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  const flush = async () => {
    const patch = pending.current
    pending.current = {}
    try {
      const updated = await api.patchMe(patch)
      setError(null)
      await mutate(['dashboard'], (d: Dashboard | undefined) => (d ? { ...d, user: { ...d.user, ...updated } } : d), {
        revalidate: true,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save settings.')
      setLocal(user)
    }
  }

  const update = (patch: Patch, debounce = 0) => {
    setLocal((u) => ({ ...u, ...patch }))
    pending.current = { ...pending.current, ...patch }
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(flush, debounce)
  }

  return (
    <Section title="Alerts">
      <Card>
        <SettingRow
          title="Pause monitoring"
          description="Stop checking your commutes and sending alerts."
          control={
            <Switch checked={local.monitoring_paused} onChange={(v) => update({ monitoring_paused: v })} label="Pause monitoring" />
          }
        />
        <Divider />
        <div className="flex flex-col gap-2 px-5 py-4">
          <Text variant="callout">Quiet hours</Text>
          <Text variant="footnote" tone="secondary">
            No push alerts between these times.
          </Text>
          <div className="flex gap-3">
            <TimeField label="From" value={local.quiet_start} onChange={(v) => update({ quiet_start: v }, 600)} />
            <TimeField label="To" value={local.quiet_end} onChange={(v) => update({ quiet_end: v }, 600)} />
          </div>
        </div>
        <Divider />
        <SettingRow
          title="Alert me when my commute is at least"
          description="slower than my normal"
          control={
            <Stepper
              label="Alert threshold"
              unit="min"
              min={1}
              max={30}
              value={local.alert_threshold_min}
              onChange={(v) => update({ alert_threshold_min: v }, 500)}
            />
          }
        />
        <Divider />
        <SettingRow
          title="Only suggest routes at least"
          description="better than my usual"
          control={
            <Stepper
              label="Minimum gain"
              unit="min"
              min={1}
              max={30}
              value={local.min_gain_min}
              onChange={(v) => update({ min_gain_min: v }, 500)}
            />
          }
        />
      </Card>
      {error && (
        <Text variant="footnote" tone="attention" role="alert" className="px-1">
          {error}
        </Text>
      )}
    </Section>
  )
}
