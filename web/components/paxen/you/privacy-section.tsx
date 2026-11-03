'use client'

import { useState } from 'react'
import { History, ShieldCheck, UserX } from 'lucide-react'
import { api, tokenStore } from '@/lib/api'
import { activeTripStore, revalidateAll } from '@/lib/hooks'
import { Card, Divider, Section } from '../primitives/card'
import { ConfirmSheet } from '../primitives/sheet'
import { Text } from '../primitives/text'

function ActionRow({ icon, label, danger, onClick }: { icon: React.ReactNode; label: string; danger?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-h-14 w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-px-surface-sunken"
    >
      <span className={danger ? 'text-px-attention' : 'text-px-text-secondary'}>{icon}</span>
      <Text variant="callout" tone={danger ? 'attention' : 'primary'} style={{ fontWeight: 600 }}>
        {label}
      </Text>
    </button>
  )
}

export function PrivacySection() {
  const [confirm, setConfirm] = useState<'history' | 'account' | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const run = async () => {
    setBusy(true)
    try {
      if (confirm === 'history') {
        const r = await api.deleteHistory()
        activeTripStore.set(null)
        setMessage(`Deleted ${r.trips_deleted} trips and ${r.alerts_deleted} alerts.`)
        await revalidateAll()
      } else if (confirm === 'account') {
        await api.deleteMe()
        activeTripStore.set(null)
        tokenStore.clear()
        window.location.assign('/')
        return
      }
      setConfirm(null)
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Something went wrong.')
      setConfirm(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section title="Privacy">
      <Card>
        <div className="flex gap-3 px-5 py-4">
          <ShieldCheck className="mt-0.5 size-5 shrink-0 text-px-success" aria-hidden />
          <Text variant="footnote" tone="secondary" className="text-pretty">
            Your account is anonymous — no email or phone number. Paxen stores your places to ~10 m precision and uses
            your schedule, not background location. Journey history is only used to learn your normal.
          </Text>
        </div>
        <Divider />
        <ActionRow icon={<History className="size-5" aria-hidden />} label="Clear journey history" onClick={() => setConfirm('history')} />
        <Divider />
        <ActionRow icon={<UserX className="size-5" aria-hidden />} label="Delete account" danger onClick={() => setConfirm('account')} />
      </Card>
      {message && (
        <Text variant="footnote" tone="secondary" role="status" className="px-1">
          {message}
        </Text>
      )}
      <ConfirmSheet
        open={confirm === 'history'}
        onClose={() => setConfirm(null)}
        title="Clear journey history?"
        body="This deletes your logged trips and alerts. Paxen will need a few days to learn your normal again."
        confirmLabel="Clear history"
        onConfirm={run}
        loading={busy}
      />
      <ConfirmSheet
        open={confirm === 'account'}
        onClose={() => setConfirm(null)}
        title="Delete your account?"
        body="Your places, commutes, trips and alerts are permanently deleted. This can't be undone."
        confirmLabel="Delete account"
        onConfirm={run}
        loading={busy}
      />
    </Section>
  )
}
