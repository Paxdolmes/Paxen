'use client'

import { useState } from 'react'
import { Briefcase, Home, Pencil, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { DAY_LABELS, fmtDays, PREFERENCE_LABELS, PREFERENCES } from '@/lib/format'
import { revalidateAll } from '@/lib/hooks'
import type { Commute, Place, PlaceSearchResult, Preference } from '@/lib/types'
import { Button } from '../primitives/button'
import { Card, Divider, Section } from '../primitives/card'
import { ChoiceChip } from '../primitives/chip'
import { SelectField, SettingRow, Switch, TimeField } from '../primitives/controls'
import { ConfirmSheet, Sheet } from '../primitives/sheet'
import { Text } from '../primitives/text'
import { PlaceSearch } from '../place-search'

function uniquePlaces(commutes: Commute[]): Place[] {
  const map = new Map<string, Place>()
  for (const c of commutes) for (const p of [c.origin, c.dest]) map.set(p.id, p)
  return [...map.values()].sort((a, b) => (a.label === 'home' ? -1 : b.label === 'home' ? 1 : 0))
}

function PlaceEditor({ place, onClose }: { place: Place; onClose: () => void }) {
  const [sel, setSel] = useState<PlaceSearchResult | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const save = async () => {
    if (!sel) return
    setSaving(true)
    setError(null)
    try {
      await api.patchPlace(place.id, { name: sel.name, lat: sel.lat, lon: sel.lon, source: 'manual' })
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
      title={`Change ${place.label === 'home' ? 'Home' : place.label === 'work' ? 'Work' : place.name}`}
      footer={
        <Button block onClick={save} disabled={!sel} loading={saving}>
          Save
        </Button>
      }
    >
      <div className="flex flex-col gap-3">
        <Text variant="footnote" tone="secondary">
          Currently: {place.name}
        </Text>
        <PlaceSearch label="Search for a place" placeholder="Station, street or postcode" selected={sel} onSelect={setSel} />
        {error && (
          <Text variant="footnote" tone="attention" role="alert">
            {error}
          </Text>
        )}
      </div>
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
        <Button block onClick={save} disabled={invalid} loading={saving}>
          Save changes
        </Button>
      }
    >
      <div className="flex flex-col gap-5">
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2">
            <Text variant="caption" tone="secondary">
              Days
            </Text>
          </legend>
          <div className="flex flex-wrap gap-2">
            {DAY_LABELS.map((d, i) => (
              <ChoiceChip
                key={d}
                selected={days.includes(i)}
                onClick={() => setDays((v) => (v.includes(i) ? v.filter((x) => x !== i) : [...v, i].sort()))}
              >
                {d}
              </ChoiceChip>
            ))}
          </div>
        </fieldset>
        <div className="flex gap-3">
          <TimeField label="Leave from" value={start} onChange={setStart} />
          <TimeField label="Until" value={end} onChange={setEnd} />
        </div>
        <SelectField
          label="Route preference"
          value={pref}
          options={PREFERENCES.map((p) => ({ value: p, label: PREFERENCE_LABELS[p] }))}
          onChange={setPref}
        />
        {invalid && (
          <Text variant="footnote" tone="watch">
            Pick at least one day and a window that ends after it starts.
          </Text>
        )}
        {error && (
          <Text variant="footnote" tone="attention" role="alert">
            {error}
          </Text>
        )}
      </div>
    </Sheet>
  )
}

export function CommuteSettings({ commutes }: { commutes: Commute[] }) {
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
          {places.map((p, i) => {
            const Icon = p.label === 'work' ? Briefcase : Home
            return (
              <div key={p.id}>
                {i > 0 && <Divider />}
                <div className="flex items-center gap-3 px-5 py-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-px-brand-soft text-px-on-brand-soft">
                    <Icon className="size-5" aria-hidden />
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col">
                    <Text variant="callout" style={{ fontWeight: 600 }}>
                      {p.label === 'home' ? 'Home' : p.label === 'work' ? 'Work' : 'Place'}
                    </Text>
                    <Text variant="footnote" tone="secondary" className="truncate">
                      {p.name}
                    </Text>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => setEditPlace(p)} aria-label={`Edit ${p.name}`}>
                    <Pencil className="size-4" aria-hidden />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setDeletePlace(p)} aria-label={`Delete ${p.name}`}>
                    <Trash2 className="size-4" aria-hidden />
                  </Button>
                </div>
              </div>
            )
          })}
        </Card>
        <Text variant="footnote" tone="tertiary" className="px-1 text-pretty">
          Paxen only stores your places to ~10 m precision.
        </Text>
      </Section>

      <Section title="Your commutes">
        <Card>
          {commutes.map((c, i) => (
            <div key={c.id}>
              {i > 0 && <Divider />}
              <button
                type="button"
                onClick={() => setEditCommute(c)}
                className="flex w-full items-center justify-between gap-3 px-5 pb-1 pt-4 text-left"
              >
                <div className="flex min-w-0 flex-col gap-0.5">
                  <Text variant="headline" as="span">
                    {c.name}
                  </Text>
                  <Text variant="footnote" tone="secondary" tabular>
                    {fmtDays(c.days)} · {c.window_start}–{c.window_end} · {PREFERENCE_LABELS[c.preference]}
                  </Text>
                  {c.usual_summary && (
                    <Text variant="footnote" tone="tertiary">
                      Usual: {c.usual_summary}
                    </Text>
                  )}
                </div>
                <Pencil className="size-4 shrink-0 text-px-text-tertiary" aria-hidden />
                <span className="sr-only">Edit {c.name}</span>
              </button>
              <SettingRow
                title="Alerts for this commute"
                control={
                  <Switch
                    checked={c.alerts_enabled}
                    onChange={(v) => toggleAlerts(c, v)}
                    disabled={toggling === c.id}
                    label={`Alerts for ${c.name}`}
                  />
                }
              />
            </div>
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
