'use client'

import { useEffect, useState } from 'react'
import { BellRing, DatabaseZap } from 'lucide-react'
import { api } from '@/lib/api'
import { revalidateAll, useScenarios } from '@/lib/hooks'
import { Button } from '../primitives/button'
import { Card, Divider, Section, Skeleton } from '../primitives/card'
import { SelectField } from '../primitives/controls'
import { Text } from '../primitives/text'

const SCENARIO_LABELS: Record<string, string> = {
  auto: 'Auto (time-of-day)',
  normal: 'Good service everywhere',
  'victoria-severe': 'Victoria line severe delays',
  'victoria-suspended': 'Victoria line suspended',
  'central-minor': 'Central line minor delays',
  'weaver-suspended': 'Weaver line suspended',
  mixed: 'Mixed disruption',
}

function SeedProgress() {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const start = Date.now()
    const t = setInterval(() => setElapsed((Date.now() - start) / 1000), 200)
    return () => clearInterval(t)
  }, [])
  const pct = Math.min(95, (elapsed / 10) * 100)
  return (
    <div className="flex flex-col gap-1.5" role="status" aria-live="polite">
      <div
        className="h-2 overflow-hidden rounded-full bg-px-surface-sunken"
        role="progressbar"
        aria-label="Backfilling history"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
      >
        <div className="h-full rounded-full bg-px-brand transition-[width] duration-200" style={{ width: `${pct}%` }} />
      </div>
      <Text variant="caption" tone="secondary" tabular>
        Simulating weeks of trips… {Math.floor(elapsed)} s
      </Text>
    </div>
  )
}

export function SimulatorSection() {
  const { data, isLoading, mutate } = useScenarios(true)
  const [busy, setBusy] = useState<'scenario' | 'seed' | 'check' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const act = async (kind: 'scenario' | 'seed' | 'check', fn: () => Promise<unknown>, done: string) => {
    setBusy(kind)
    setMessage(null)
    try {
      await fn()
      await revalidateAll()
      setMessage(done)
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'That didn’t work.')
    } finally {
      setBusy(null)
    }
  }

  const options = (data?.scenarios ?? []).map((s) => ({ value: s, label: SCENARIO_LABELS[s] ?? s }))
  const current = data?.current ?? options[0]?.value ?? ''

  return (
    <Section title="Simulator">
      <Card className="flex flex-col gap-4 p-5">
        <Text variant="footnote" tone="secondary" className="text-pretty">
          You&apos;re connected to a simulated London network. Change what&apos;s happening and see how Paxen reacts.
        </Text>
        {isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : options.length > 0 ? (
          <SelectField
            label="Scenario"
            value={current}
            options={options}
            onChange={(s) =>
              act(
                'scenario',
                async () => {
                  await api.setScenario(s)
                  await mutate({ scenarios: data?.scenarios ?? [], current: s }, { revalidate: false })
                },
                `Scenario set to ${SCENARIO_LABELS[s] ?? s}.`,
              )
            }
          />
        ) : (
          <Text variant="footnote" tone="tertiary">
            No scenarios available.
          </Text>
        )}
        <Divider />
        <div className="flex flex-col gap-2">
          <Button
            variant="secondary"
            block
            icon={<DatabaseZap className="size-5" aria-hidden />}
            loading={busy === 'seed'}
            disabled={busy !== null}
            onClick={() => act('seed', api.seed, 'History backfilled. Your normal has been recalculated.')}
          >
            Backfill history
          </Button>
          {busy === 'seed' && <SeedProgress />}
          <Button
            variant="secondary"
            block
            icon={<BellRing className="size-5" aria-hidden />}
            loading={busy === 'check'}
            disabled={busy !== null}
            onClick={() => act('check', api.checkNow, 'Checked your commutes. Any new alerts are in the Alerts tab.')}
          >
            Check for alerts now
          </Button>
        </div>
        {message && (
          <Text variant="footnote" tone="secondary" role="status">
            {message}
          </Text>
        )}
      </Card>
    </Section>
  )
}
