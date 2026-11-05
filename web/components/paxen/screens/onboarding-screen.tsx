'use client'

import { useState } from 'react'
import { ArrowLeft, BellRing, Gauge, ShieldCheck } from 'lucide-react'
import { api, tokenStore } from '@/lib/api'
import { DAY_LABELS, PREFERENCE_LABELS, PREFERENCES } from '@/lib/format'
import type { ChosenStop, PlaceSearchResult, Preference } from '@/lib/types'
import { Wordmark } from '../app-header'
import { PlaceSearch } from '../place-search'
import { StopPicker } from '../stop-picker'
import { Button } from '../primitives/button'
import { ChoiceChip } from '../primitives/chip'
import { TimeField } from '../primitives/controls'
import { Segmented } from '../primitives/segmented'
import { Text, textStyle } from '../primitives/text'

type Step = 'welcome' | 'places' | 'routine'
const STEPS: Step[] = ['places', 'routine']

function Progress({ step }: { step: Step }) {
  const i = STEPS.indexOf(step)
  return (
    <div className="flex flex-1 items-center gap-3">
      <div className="flex flex-1 items-center gap-1.5" aria-hidden>
        {STEPS.map((s, j) => (
          <span key={s} className={`h-1.5 flex-1 rounded-full ${j <= i ? 'bg-px-brand' : 'bg-px-border'}`} />
        ))}
      </div>
      <Text variant="footnote" tone="secondary" className="shrink-0 tabular">
        Step {i + 1} of {STEPS.length}
      </Text>
    </div>
  )
}

function Welcome({ onStart, busy, error }: {
  onStart: () => void
  busy: boolean
  error: string | null
}) {
  const points = [
    { icon: Gauge, text: 'Learns your usual trip to work and back.' },
    { icon: BellRing, text: 'Tells you before you leave if today is different, and what to take instead.' },
    { icon: ShieldCheck, text: 'No account to create. Location is only used during a live trip, never stored.' },
  ]
  return (
    <div className="flex flex-1 flex-col gap-8 pt-10">
      <div className="flex flex-col gap-4">
        <Wordmark size={36} />
        <Text variant="display" as="h1" className="text-balance">
          Know before you leave if your commute is off.
        </Text>
      </div>
      <ul className="flex flex-col gap-4">
        {points.map(({ icon: Icon, text }) => (
          <li key={text} className="flex gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-px-brand-soft text-px-on-brand-soft">
              <Icon className="size-5" aria-hidden />
            </span>
            <Text variant="callout" tone="secondary" className="pt-1.5 text-pretty">
              {text}
            </Text>
          </li>
        ))}
      </ul>
      <div className="mt-auto flex flex-col gap-2 pb-4">
        {error && (
          <Text variant="footnote" tone="attention" role="alert">
            {error}
          </Text>
        )}
        <Button block onClick={onStart} loading={busy}>
          Get started
        </Button>
        <Text variant="footnote" tone="secondary" className="text-center">
          Takes about a minute.
        </Text>
      </div>
    </div>
  )
}

export function OnboardingScreen({ onStart, onDone }: { onStart: () => void; onDone: () => void }) {
  const [step, setStep] = useState<Step>(() => (tokenStore.get() ? 'places' : 'welcome'))
  const [home, setHomePlace] = useState<PlaceSearchResult | null>(null)
  const [work, setWorkPlace] = useState<PlaceSearchResult | null>(null)
  const [homeStops, setHomeStops] = useState<ChosenStop[]>([])
  const [workStops, setWorkStops] = useState<ChosenStop[]>([])
  // A different place means a different set of nearby stations.
  const setHome = (p: PlaceSearchResult) => { setHomePlace(p); setHomeStops([]) }
  const setWork = (p: PlaceSearchResult) => { setWorkPlace(p); setWorkStops([]) }
  const [days, setDays] = useState([0, 1, 2, 3, 4])
  const [mStart, setMStart] = useState('08:00')
  const [mEnd, setMEnd] = useState('08:45')
  const [eStart, setEStart] = useState('17:30')
  const [eEnd, setEEnd] = useState('18:15')
  const [pref, setPref] = useState<Preference>('balanced')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      if (!tokenStore.get()) {
        const { token } = await api.createUser()
        onStart()
        tokenStore.set(token)
      }
      setStep('places')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not get started.')
    } finally {
      setBusy(false)
    }
  }

  const submit = async () => {
    if (!home || !work) return
    setBusy(true)
    setError(null)
    try {
      await api.onboarding({
        home: { label: 'home', name: home.name, lat: home.lat, lon: home.lon, source: 'manual', stops: homeStops },
        work: { label: 'work', name: work.name, lat: work.lat, lon: work.lon, source: 'manual', stops: workStops },
        days,
        morning: { start: mStart, end: mEnd },
        evening: { start: eStart, end: eEnd },
        preference: pref,
      })
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save your routine.')
    } finally {
      setBusy(false)
    }
  }

  const back = () => setStep('places')
  const invalidRoutine = days.length === 0 || mStart >= mEnd || eStart >= eEnd

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[430px] flex-col bg-px-canvas px-5 pb-safe pt-safe">
      {step === 'welcome' ? (
        <Welcome onStart={start} busy={busy} error={error} />
      ) : (
        <div className="flex flex-1 flex-col gap-6 pt-4">
          <div className="flex items-center gap-3">
            {step === 'routine' ? (
              <button
                type="button"
                onClick={back}
                aria-label="Back"
                className="-ml-2 flex size-11 items-center justify-center rounded-full text-px-text hover:bg-px-surface-sunken"
              >
                <ArrowLeft className="size-5" aria-hidden />
              </button>
            ) : (
              <span className="flex h-11 shrink-0 items-center">
                <Wordmark size={20} />
              </span>
            )}
            <div className="flex-1">
              <Progress step={step} />
            </div>
          </div>

          {step === 'places' && (
            <section className="flex flex-col gap-6" aria-labelledby="ob-places">
              <div className="flex flex-col gap-2">
                <Text variant="title1" as="h1" id="ob-places">
                  Where do you commute?
                </Text>
                <Text variant="callout" tone="secondary" className="text-pretty">
                  A station name or postcode is enough. You can change this later.
                </Text>
              </div>
              <div className="flex flex-col gap-4">
                <PlaceSearch label="Home" placeholder="Home: station or postcode" selected={home} onSelect={setHome} autoFocus />
                {home && (
                  <StopPicker lat={home.lat} lon={home.lon} value={homeStops} onChange={setHomeStops} placeLabel="home" />
                )}
              </div>
              {home && (
                <div className="flex flex-col gap-4">
                  <PlaceSearch label="Work" placeholder="Work: station or postcode" selected={work} onSelect={setWork} autoFocus />
                  {work && (
                    <StopPicker lat={work.lat} lon={work.lon} value={workStops} onChange={setWorkStops} placeLabel="work" />
                  )}
                </div>
              )}
            </section>
          )}

          {step === 'routine' && (
            <section className="flex flex-col gap-6" aria-labelledby="ob-routine">
              <div className="flex flex-col gap-2">
                <Text variant="title1" as="h1" id="ob-routine">
                  Your routine
                </Text>
                <Text variant="callout" tone="secondary" className="text-pretty">
                  We&apos;ve filled in a typical commute. Change anything that&apos;s off.
                </Text>
              </div>
              <fieldset className="flex flex-col">
                <legend className="mb-2">
                  <Text variant="subhead" as="span" tone="secondary">
                    Days you commute
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
              <fieldset className="flex flex-col">
                <legend className="mb-2">
                  <Text variant="subhead" as="span" tone="secondary">
                    Morning: leave home between
                  </Text>
                </legend>
                <div className="flex gap-3">
                  <TimeField label="From" value={mStart} onChange={setMStart} />
                  <TimeField label="To" value={mEnd} onChange={setMEnd} />
                </div>
              </fieldset>
              <fieldset className="flex flex-col">
                <legend className="mb-2">
                  <Text variant="subhead" as="span" tone="secondary">
                    Evening: leave work between
                  </Text>
                </legend>
                <div className="flex gap-3">
                  <TimeField label="From" value={eStart} onChange={setEStart} />
                  <TimeField label="To" value={eEnd} onChange={setEEnd} />
                </div>
              </fieldset>
              <div className="flex flex-col gap-2">
                <Text variant="subhead" tone="secondary">
                  What matters most?
                </Text>
                <Segmented
                  label="What matters most"
                  value={pref}
                  scroll
                  options={PREFERENCES.map((p) => ({ value: p, label: PREFERENCE_LABELS[p] }))}
                  onChange={setPref}
                />
              </div>
              {invalidRoutine && (
                <Text variant="footnote" tone="watch">
                  Pick at least one day, and make sure each window ends after it starts.
                </Text>
              )}
            </section>
          )}

          <div className="mt-auto flex flex-col gap-2 pb-4 pt-4">
            {error && (
              <Text variant="footnote" tone="attention" role="alert">
                {error}
              </Text>
            )}
            {step === 'places' && (
              <Button block disabled={!home || !work} onClick={() => setStep('routine')}>
                Continue
              </Button>
            )}
            {step === 'routine' && (
              <Button block disabled={invalidRoutine} loading={busy} onClick={submit}>
                Done, show my commute
              </Button>
            )}
          </div>
        </div>
      )}
    </main>
  )
}
