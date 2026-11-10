import { useEffect, useRef, useState } from 'react'
import { Linking, View } from 'react-native'
import { router } from 'expo-router'
import { BellRing, Briefcase, DatabaseZap, History, Home, Pencil, ShieldCheck, Trash2, UserX } from 'lucide-react-native'
import { mutate } from 'swr'
import { DAY_LABELS, fmtDays, fmtPct, PREFERENCE_LABELS, PREFERENCES } from '@/shared/format'
import { radii } from '@/shared/paxen-tokens'
import type { AutoTripStats, ChosenStop, Commute, Dashboard, Insights, Place, PlaceSearchResult, Preference, User } from '@/shared/types'
import { api, tokenStore } from '@/lib/api'
import { activeTripStore, revalidateAll, useInsights, useScenarios } from '@/lib/hooks'
import { autoTripsPermission, disableAutoTrips, enableAutoTrips, syncGeofences } from '@/lib/autotrips'
import { disablePush, enablePush, pushPermission, type PushPermission } from '@/lib/push'
import { usePalette } from '@/lib/theme'
import { SelectField, SettingRow, Stepper, Switch, TimeField } from './controls'
import { PlaceSearch, StopPicker } from './places'
import { ConfirmSheet, Sheet } from './sheet'
import { Text } from './text'
import { Button, Card, ChoiceChip, Divider, ErrorState, ErrorText, Section, Skeleton } from './ui'

/* ---------- places and commutes ---------- */

function uniquePlaces(commutes: Commute[]): Place[] {
  const map = new Map<string, Place>()
  for (const c of commutes) for (const pl of [c.origin, c.dest]) map.set(pl.id, pl)
  return [...map.values()].sort((a, b) => (a.label === 'home' ? -1 : b.label === 'home' ? 1 : 0))
}

function DayPicker({ days, onChange }: { days: number[]; onChange: (d: number[]) => void }) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
      {DAY_LABELS.map((d, i) => (
        <ChoiceChip key={d} selected={days.includes(i)} onPress={() => onChange(days.includes(i) ? days.filter((x) => x !== i) : [...days, i].sort())}>
          {d}
        </ChoiceChip>
      ))}
    </View>
  )
}

function PlaceEditor({ place, onClose }: { place: Place; onClose: () => void }) {
  const [sel, setSel] = useState<PlaceSearchResult | null>(null)
  const [stops, setStops] = useState<ChosenStop[]>(place.stops ?? [])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const label = place.label === 'home' ? 'Home' : place.label === 'work' ? 'Work' : place.name
  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await api.patchPlace(place.id, { ...(sel ? { name: sel.name, lat: sel.lat, lon: sel.lon, source: 'manual' as const } : {}), stops })
      if (sel && (await autoTripsPermission()) === 'always') await syncGeofences().catch(() => {}) // watch the new address
      await revalidateAll()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save this place.')
    } finally {
      setSaving(false)
    }
  }
  return (
    <Sheet
      open
      onClose={onClose}
      title={`${label}: address and stations`}
      footer={
        <Button block onPress={save} loading={saving}>
          Save
        </Button>
      }
    >
      <View style={{ gap: 20 }}>
        <View style={{ gap: 12 }}>
          <Text variant="footnote" tone="secondary">
            {sel ? `New address: ${sel.name}` : `Address: ${place.name}`}
          </Text>
          <PlaceSearch
            label="Search for a new address"
            placeholder="Change address: postcode, street or station"
            selected={sel}
            onSelect={(r) => {
              setSel(r)
              setStops([]) // new address, new nearby stations
            }}
          />
        </View>
        <StopPicker lat={sel?.lat ?? place.lat} lon={sel?.lon ?? place.lon} value={stops} onChange={setStops} placeLabel={label.toLowerCase()} />
        <ErrorText>{error}</ErrorText>
      </View>
    </Sheet>
  )
}

function CommuteEditor({ commute, onClose }: { commute: Commute; onClose: () => void }) {
  const [days, setDays] = useState(commute.days)
  const [start, setStart] = useState(commute.window_start)
  const [end, setEnd] = useState(commute.window_end)
  const [pref, setPref] = useState<Preference>(commute.preference)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const invalid = days.length === 0 || start >= end
  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      await api.patchCommute(commute.id, { days, window_start: start, window_end: end, preference: pref })
      await revalidateAll()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save this commute.')
    } finally {
      setSaving(false)
    }
  }
  return (
    <Sheet
      open
      onClose={onClose}
      title={commute.name}
      footer={
        <Button block onPress={save} disabled={invalid} loading={saving}>
          Save changes
        </Button>
      }
    >
      <View style={{ gap: 20 }}>
        <View style={{ gap: 8 }}>
          <Text variant="caption" tone="secondary">
            Days
          </Text>
          <DayPicker days={days} onChange={setDays} />
        </View>
        <View style={{ flexDirection: 'row', gap: 12 }}>
          <TimeField label="Leave from" value={start} onChange={setStart} />
          <TimeField label="Until" value={end} onChange={setEnd} />
        </View>
        <SelectField label="Route preference" value={pref} options={PREFERENCES.map((v) => ({ value: v, label: PREFERENCE_LABELS[v] }))} onChange={setPref} />
        {invalid && (
          <Text variant="footnote" tone="watch">
            Pick at least one day and a window that ends after it starts.
          </Text>
        )}
        <ErrorText>{error}</ErrorText>
      </View>
    </Sheet>
  )
}

export function CommuteSettings({ commutes }: { commutes: Commute[] }) {
  const p = usePalette()
  const [editPlace, setEditPlace] = useState<Place | null>(null)
  const [deletePlace, setDeletePlace] = useState<Place | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [editCommute, setEditCommute] = useState<Commute | null>(null)
  const [toggling, setToggling] = useState<string | null>(null)
  const places = uniquePlaces(commutes)

  const toggleAlerts = async (c: Commute, v: boolean) => {
    setToggling(c.id)
    try {
      await api.patchCommute(c.id, { alerts_enabled: v })
      await revalidateAll()
    } finally {
      setToggling(null)
    }
  }
  const confirmDelete = async () => {
    if (!deletePlace) return
    setDeleting(true)
    try {
      await api.deletePlace(deletePlace.id)
      await revalidateAll()
      setDeletePlace(null)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <>
      <Section title="Your places">
        <Card>
          {places.map((pl, i) => {
            const Icon = pl.label === 'work' ? Briefcase : Home
            return (
              <View key={pl.id}>
                {i > 0 && <Divider />}
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 20, paddingVertical: 12 }}>
                  <View style={{ width: 40, height: 40, borderRadius: 20, backgroundColor: p.brandSoft, alignItems: 'center', justifyContent: 'center' }}>
                    <Icon size={20} color={p.onBrandSoft} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text variant="callout" style={{ fontWeight: '600' }}>
                      {pl.label === 'home' ? 'Home' : pl.label === 'work' ? 'Work' : 'Place'}
                    </Text>
                    <Text variant="footnote" tone="secondary" numberOfLines={1}>
                      {pl.name}
                    </Text>
                    <Text variant="footnote" tone="tertiary" numberOfLines={1}>
                      {pl.stops?.length ? `Stations: ${pl.stops.map((st) => st.name).join(', ')}` : 'Stations: Paxen chooses'}
                    </Text>
                  </View>
                  <Button variant="ghost" size="sm" accessibilityLabel={`Edit ${pl.name}`} onPress={() => setEditPlace(pl)} icon={(c) => <Pencil size={16} color={c} />} />
                  <Button variant="ghost" size="sm" accessibilityLabel={`Delete ${pl.name}`} onPress={() => setDeletePlace(pl)} icon={(c) => <Trash2 size={16} color={c} />} />
                </View>
              </View>
            )
          })}
        </Card>
        <Text variant="footnote" tone="tertiary" style={{ paddingHorizontal: 4 }}>
          Paxen only stores your places to ~10 m precision.
        </Text>
      </Section>

      <Section title="Your commutes">
        <Card>
          {commutes.map((c, i) => (
            <View key={c.id}>
              {i > 0 && <Divider />}
              <Button variant="ghost" accessibilityLabel={`Edit ${c.name}`} onPress={() => setEditCommute(c)} style={{ height: undefined, borderRadius: 0, paddingHorizontal: 20, paddingTop: 16, paddingBottom: 4, alignSelf: 'stretch', justifyContent: 'space-between' }}>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text variant="headline">{c.name}</Text>
                  <Text variant="footnote" tone="secondary" tabular>
                    {fmtDays(c.days)} · {c.window_start}–{c.window_end} · {PREFERENCE_LABELS[c.preference]}
                  </Text>
                  {c.usual_summary ? (
                    <Text variant="footnote" tone="tertiary">
                      Usual: {c.usual_summary}
                    </Text>
                  ) : null}
                </View>
                <Pencil size={16} color={p.textTertiary} />
              </Button>
              <SettingRow
                title="Alerts for this commute"
                control={<Switch checked={c.alerts_enabled} onChange={(v) => toggleAlerts(c, v)} disabled={toggling === c.id} label={`Alerts for ${c.name}`} />}
              />
            </View>
          ))}
        </Card>
      </Section>

      {editPlace && <PlaceEditor place={editPlace} onClose={() => setEditPlace(null)} />}
      {editCommute && <CommuteEditor commute={editCommute} onClose={() => setEditCommute(null)} />}
      <ConfirmSheet
        open={!!deletePlace}
        onClose={() => setDeletePlace(null)}
        title={`Delete ${deletePlace?.name ?? 'place'}?`}
        body="Commutes that use this place will stop being monitored until you set it again."
        confirmLabel="Delete place"
        onConfirm={confirmDelete}
        loading={deleting}
      />
    </>
  )
}

export { DayPicker }

/* ---------- automatic trips ---------- */

const SKIP_WORDS: Record<string, string> = {
  too_slow: 'a stop on the way',
  too_fast: 'impossibly quick',
  returned: 'went back where you started',
}

export function autoTripSummary(st: AutoTripStats | undefined): string | null {
  if (!st) return null
  const parts: string[] = []
  if (st.recorded) parts.push(`${st.recorded} trip${st.recorded === 1 ? '' : 's'} logged`)
  const skipped = Object.entries(st.skipped ?? {}).filter(([, n]) => n > 0)
  if (skipped.length)
    parts.push(`${skipped.reduce((a, [, n]) => a + n, 0)} left out (${skipped.map(([r, n]) => `${n} ${SKIP_WORDS[r] ?? r}`).join(', ')})`)
  return parts.length ? parts.join(' · ') : null
}

export function AutoTripsSection({ user }: { user: User }) {
  const [on, setOn] = useState(!!user.auto_trips)
  const [shownOn, setShownOn] = useState(!!user.auto_trips)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [needsAlways, setNeedsAlways] = useState(false)
  if (shownOn !== !!user.auto_trips) {
    setShownOn(!!user.auto_trips)
    setOn(!!user.auto_trips)
  }

  useEffect(() => {
    if (!user.auto_trips) return
    autoTripsPermission()
      .then((p) => setNeedsAlways(p !== 'always' && p !== 'unsupported'))
      .catch(() => {})
  }, [user.auto_trips])

  const toggle = async (v: boolean) => {
    setBusy(true)
    setNote(null)
    try {
      if (v) {
        const res = await enableAutoTrips()
        setNeedsAlways(res === 'needs-always' || res === 'denied')
        if (res !== 'on') {
          setNote(res === 'unsupported' ? 'Automatic trips need the iPhone app.' : null)
          return
        }
      } else {
        await disableAutoTrips()
        setNeedsAlways(false)
      }
      setOn(v)
      await mutate(['dashboard'])
    } catch (e) {
      setNote(e instanceof Error ? e.message : 'Could not change automatic trips.')
    } finally {
      setBusy(false)
    }
  }

  const summary = autoTripSummary(user.auto_trip_stats)
  return (
    <Section title="Automatic trips">
      <Card>
        <SettingRow
          title="Log my commutes automatically"
          description="Paxen notices when you leave Home or Work and reach the other, and times the trip. Trips with a stop on the way are left out."
          control={<Switch checked={on} onChange={toggle} label="Log my commutes automatically" disabled={busy} />}
        />
        {(needsAlways || note || (on && summary)) && (
          <View style={{ gap: 8, paddingHorizontal: 20, paddingBottom: 16, alignItems: 'flex-start' }}>
            {needsAlways && (
              <>
                <Text variant="footnote" tone="secondary">
                  To notice trips while Paxen is closed, the iPhone needs Location set to Always for Paxen. Only the time you leave or
                  reach Home and Work is sent, never where you are.
                </Text>
                <Button variant="secondary" size="sm" onPress={() => Linking.openSettings()}>
                  Open Settings
                </Button>
              </>
            )}
            {note && (
              <Text variant="footnote" tone="secondary">
                {note}
              </Text>
            )}
            {on && summary && (
              <Text variant="footnote" tone="secondary">
                {summary}
              </Text>
            )}
          </View>
        )}
      </Card>
    </Section>
  )
}

/* ---------- alerts ---------- */

type Patch = Partial<Pick<User, 'monitoring_paused' | 'quiet_start' | 'quiet_end' | 'alert_threshold_min' | 'min_gain_min'>>

export function AlertSettings({ user }: { user: User }) {
  const [local, setLocal] = useState(user)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pending = useRef<Patch>({})

  // When the saved settings change (after a save or refresh), show them.
  const [shown, setShown] = useState(user)
  if (shown !== user) {
    setShown(user)
    setLocal(user)
  }
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  const flush = async () => {
    const patch = pending.current
    pending.current = {}
    try {
      const updated = await api.patchMe(patch)
      setError(null)
      await mutate(['dashboard'], (d: Dashboard | undefined) => (d ? { ...d, user: { ...d.user, ...updated } } : d), { revalidate: true })
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
        <PushRow enabled={local.push_enabled} onChange={(push_enabled) => setLocal((u) => ({ ...u, push_enabled }))} />
        <Divider />
        <SettingRow
          title="Pause monitoring"
          description="Stop checking your commutes and sending alerts."
          control={<Switch checked={local.monitoring_paused} onChange={(v) => update({ monitoring_paused: v })} label="Pause monitoring" />}
        />
        <Divider />
        <View style={{ gap: 8, paddingHorizontal: 20, paddingVertical: 16 }}>
          <Text variant="callout">Quiet hours</Text>
          <Text variant="footnote" tone="secondary">
            No push alerts between these times.
          </Text>
          <View style={{ flexDirection: 'row', gap: 12 }}>
            <TimeField label="From" value={local.quiet_start} onChange={(v) => update({ quiet_start: v })} />
            <TimeField label="To" value={local.quiet_end} onChange={(v) => update({ quiet_end: v })} />
          </View>
        </View>
        <Divider />
        <SettingRow
          title="Alert me when my commute is at least"
          description="slower than my normal"
          control={<Stepper label="Alert threshold" unit="min" min={1} max={30} value={local.alert_threshold_min} onChange={(v) => update({ alert_threshold_min: v }, 500)} />}
        />
        <Divider />
        <SettingRow
          title="Only suggest routes at least"
          description="better than my usual"
          control={<Stepper label="Minimum gain" unit="min" min={1} max={30} value={local.min_gain_min} onChange={(v) => update({ min_gain_min: v }, 500)} />}
        />
      </Card>
      {error && (
        <View style={{ paddingHorizontal: 4 }}>
          <ErrorText>{error}</ErrorText>
        </View>
      )}
    </Section>
  )
}

function PushRow({ enabled, onChange }: { enabled: boolean; onChange: (v: boolean) => void }) {
  const [perm, setPerm] = useState<PushPermission>('undetermined')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    pushPermission().then(setPerm).catch(() => {})
  }, [])

  const toggle = async (on: boolean) => {
    setBusy(true)
    setNote(null)
    try {
      if (on) {
        const ok = await enablePush()
        setPerm(await pushPermission())
        if (!ok) {
          setNote('Notifications weren’t allowed, so alerts will only appear in the Alerts tab.')
          return
        }
      } else {
        await disablePush()
      }
      onChange(on)
      await mutate(['dashboard'])
    } catch (e) {
      setNote(e instanceof Error ? e.message : 'Could not change notifications.')
    } finally {
      setBusy(false)
    }
  }

  const test = async () => {
    setBusy(true)
    try {
      const { result } = await api.testPush()
      setNote(result === 'sent' ? 'Test sent. It should arrive in a few seconds.' : 'That didn’t reach this phone. Turn notifications off and on again.')
    } catch (e) {
      setNote(e instanceof Error ? e.message : 'Could not send a test.')
    } finally {
      setBusy(false)
    }
  }

  const blocked = perm === 'denied'
  return (
    <View>
      <SettingRow
        title="Push notifications"
        description="Get alerts on this phone, even when Paxen is closed."
        control={<Switch checked={enabled} onChange={toggle} label="Push notifications" disabled={busy || perm === 'unsupported' || (blocked && !enabled)} />}
      />
      {(blocked || note || enabled) && (
        <View style={{ gap: 8, paddingHorizontal: 20, paddingBottom: 16, alignItems: 'flex-start' }}>
          {blocked && (
            <>
              <Text variant="footnote" tone="secondary">
                Notifications are turned off for Paxen. Allow them in Settings, then come back.
              </Text>
              <Button variant="secondary" size="sm" onPress={() => Linking.openSettings()}>
                Open Settings
              </Button>
            </>
          )}
          {note && (
            <Text variant="footnote" tone="secondary" accessibilityLiveRegion="polite">
              {note}
            </Text>
          )}
          {enabled && (
            <Button variant="ghost" size="sm" onPress={test} loading={busy}>
              Send a test notification
            </Button>
          )}
        </View>
      )}
    </View>
  )
}

/* ---------- insights ---------- */

const LEAD_ORDER = ['0-2m', '2-5m', '5-10m', '10-20m', '20m+']
const LEAD_LABELS: Record<string, string> = { '0-2m': '0–2 min', '2-5m': '2–5 min', '5-10m': '5–10 min', '10-20m': '10–20 min', '20m+': '20+ min' }

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const p = usePalette()
  return (
    <View style={{ flexBasis: '48%', flexGrow: 1, gap: 2, borderRadius: radii.md, backgroundColor: p.surfaceSunken, padding: 16 }}>
      <Text variant="title2" tabular>
        {value}
      </Text>
      <Text variant="footnote" tone="secondary">
        {label}
      </Text>
      {hint ? (
        <Text variant="caption" tone="tertiary">
          {hint}
        </Text>
      ) : null}
    </View>
  )
}

function LeadChart({ byLead }: { byLead: NonNullable<Insights['model']['by_lead']> }) {
  const p = usePalette()
  const rows = LEAD_ORDER.filter((k) => byLead[k]).map((k) => ({ k, ...byLead[k] }))
  const max = Math.max(1, ...rows.flatMap((r) => [r.provider.mae_s ?? 0, r.corrected.mae_s ?? 0]))
  const legend = (color: string, label: string) => (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
      <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: color }} />
      <Text variant="caption" tone="secondary">
        {label}
      </Text>
    </View>
  )
  return (
    <View style={{ gap: 12 }}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <Text variant="subhead">Average error by how far ahead</Text>
        <View style={{ flexDirection: 'row', gap: 12 }}>
          {legend(p.borderStrong, 'Countdown')}
          {legend(p.brand, 'Paxen')}
        </View>
      </View>
      {rows.map((r) => (
        <View key={r.k} style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          <Text variant="caption" tone="secondary" tabular style={{ width: 64 }}>
            {LEAD_LABELS[r.k] ?? r.k}
          </Text>
          <View style={{ flex: 1, gap: 4 }}>
            {(
              [
                ['Countdown', r.provider.mae_s, p.borderStrong],
                ['Paxen', r.corrected.mae_s, p.brand],
              ] as const
            ).map(([name, v, color]) =>
              v == null ? null : (
                <View key={name} accessibilityLabel={`${name}: ${Math.round(v)} seconds`} style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                  <View style={{ flex: 1, height: 10, borderRadius: 5, backgroundColor: p.surfaceSunken, overflow: 'hidden' }}>
                    <View style={{ height: '100%', width: `${(v / max) * 100}%`, borderRadius: 5, backgroundColor: color }} />
                  </View>
                  <Text variant="caption" tone="secondary" tabular style={{ width: 40, textAlign: 'right' }}>
                    {Math.round(v)} s
                  </Text>
                </View>
              ),
            )}
          </View>
        </View>
      ))}
    </View>
  )
}

export function InsightsSection() {
  const { data, error, isLoading, mutate: refetch } = useInsights()
  if (error && !data)
    return (
      <Section title="How Paxen is doing">
        <ErrorState error={error} onRetry={() => refetch()} />
      </Section>
    )
  if (isLoading || !data)
    return (
      <Section title="How Paxen is doing">
        <Skeleton style={{ height: 288, borderRadius: 20 }} />
      </Section>
    )
  const { personal: pp, model: m } = data
  const ratedUseful = pp.alerts_rated > 0 ? `${pp.alerts_rated_useful} of ${pp.alerts_rated}` : 'Not rated yet'
  return (
    <Section title="How Paxen is doing">
      <Card style={{ padding: 20, gap: 16 }}>
        <Text variant="headline">For you · last {pp.window_days} days</Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          <Stat label="Trips logged" value={String(pp.trips)} />
          <Stat label="Minutes saved" value={String(Math.round(pp.minutes_saved))} />
          <Stat label="Alerts rated useful" value={ratedUseful} />
          <Stat
            label="Trips as predicted"
            value={pp.interval_hit_rate != null ? fmtPct(pp.interval_hit_rate) : '—'}
            hint={pp.interval_hit_rate != null ? 'Arrived in the time we gave' : 'Still learning your routine'}
          />
        </View>
      </Card>
      <Card style={{ padding: 20, gap: 16 }}>
        <View style={{ gap: 4 }}>
          <Text variant="headline">How accurate are arrival times?</Text>
          <Text variant="footnote" tone="secondary">
            Live countdowns can be too optimistic for long waits. Paxen checks what really happened and adjusts.
          </Text>
        </View>
        {m.status === 'no_model' || !m.provider || !m.corrected ? (
          <Text variant="callout" tone="secondary">
            {m.message ?? 'Still collecting data. Check back soon.'}
          </Text>
        ) : (
          <>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
              <Stat
                label="Usual countdown is off by"
                value={m.provider.mae_s != null ? `${Math.round(m.provider.mae_s)} s` : '—'}
                hint={m.provider.within_2m != null ? `${fmtPct(m.provider.within_2m)} within 2 min` : undefined}
              />
              <Stat
                label="Paxen is off by"
                value={m.corrected.mae_s != null ? `${Math.round(m.corrected.mae_s)} s` : '—'}
                hint={m.corrected.within_2m != null ? `${fmtPct(m.corrected.within_2m)} within 2 min` : undefined}
              />
            </View>
            {m.by_lead && Object.keys(m.by_lead).length > 0 && (
              <>
                <Divider />
                <LeadChart byLead={m.by_lead} />
              </>
            )}
            <Text variant="caption" tone="tertiary">
              Based on {m.corrected.n.toLocaleString('en-GB')} real arrivals.
            </Text>
          </>
        )}
      </Card>
    </Section>
  )
}

/* ---------- privacy ---------- */

export function PrivacySection() {
  const p = usePalette()
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
        tokenStore.set(null)
        router.replace('/onboarding')
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

  const row = (icon: React.ReactNode, label: string, onPress: () => void, danger?: boolean) => (
    <Button variant="ghost" onPress={onPress} style={{ height: 56, borderRadius: 0, paddingHorizontal: 20, alignSelf: 'stretch', justifyContent: 'flex-start', gap: 12 }}>
      {icon}
      <Text variant="callout" tone={danger ? 'attention' : 'primary'} style={{ fontWeight: '600' }}>
        {label}
      </Text>
    </Button>
  )

  return (
    <Section title="Privacy">
      <Card>
        <View style={{ flexDirection: 'row', gap: 12, paddingHorizontal: 20, paddingVertical: 16 }}>
          <ShieldCheck size={20} color={p.success} style={{ marginTop: 2 }} />
          <Text variant="footnote" tone="secondary" style={{ flex: 1 }}>
            Your account is anonymous — no email or phone number. Paxen stores your places to ~10 m precision and never stores where you
            are. With automatic trips on, it only notes when you leave or reach Home and Work. Journey history is only used to learn your
            normal.
          </Text>
        </View>
        <Divider />
        {row(<History size={20} color={p.textSecondary} />, 'Clear journey history', () => setConfirm('history'))}
        <Divider />
        {row(<UserX size={20} color={p.attention} />, 'Delete account', () => setConfirm('account'), true)}
        <Divider />
        <Button variant="ghost" size="sm" onPress={() => Linking.openURL('https://paxen-production.up.railway.app/privacy')} style={{ alignSelf: 'stretch', borderRadius: 0, height: 48 }}>
          Privacy policy
        </Button>
      </Card>
      {message && (
        <Text variant="footnote" tone="secondary" style={{ paddingHorizontal: 4 }}>
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
        body="This deletes your places, commutes, trips and alerts from Paxen straight away. It can't be undone."
        confirmLabel="Delete account"
        onConfirm={run}
        loading={busy}
      />
    </Section>
  )
}

/* ---------- simulator (sim backend only) ---------- */

const SCENARIO_LABELS: Record<string, string> = {
  auto: 'Auto (time-of-day)',
  normal: 'Good service everywhere',
  'victoria-severe': 'Victoria line severe delays',
  'victoria-suspended': 'Victoria line suspended',
  'central-minor': 'Central line minor delays',
  'weaver-suspended': 'Weaver line suspended',
  mixed: 'Mixed disruption',
}

export function SimulatorSection() {
  const { data, isLoading, mutate: refetch } = useScenarios(true)
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
      <Card style={{ padding: 20, gap: 16 }}>
        <Text variant="footnote" tone="secondary">
          You&apos;re connected to a simulated London network. Change what&apos;s happening and see how Paxen reacts.
        </Text>
        {isLoading ? (
          <Skeleton style={{ height: 64 }} />
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
                  await refetch({ scenarios: data?.scenarios ?? [], current: s }, { revalidate: false })
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
        <View style={{ gap: 8 }}>
          <Button variant="secondary" block icon={(c) => <DatabaseZap size={20} color={c} />} loading={busy === 'seed'} disabled={busy !== null} onPress={() => act('seed', api.seed, 'History backfilled. Your normal has been recalculated.')}>
            Backfill history
          </Button>
          <Button variant="secondary" block icon={(c) => <BellRing size={20} color={c} />} loading={busy === 'check'} disabled={busy !== null} onPress={() => act('check', api.checkNow, 'Checked your commutes. Any new alerts are in the Alerts tab.')}>
            Check for alerts now
          </Button>
        </View>
        {message && (
          <Text variant="footnote" tone="secondary">
            {message}
          </Text>
        )}
      </Card>
    </Section>
  )
}
