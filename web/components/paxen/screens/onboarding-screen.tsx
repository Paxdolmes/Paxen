'use client'

import { useState } from 'react'
import { ArrowLeft, BellRing, Gauge, ShieldCheck } from 'lucide-react'
import { api, tokenStore } from '@/lib/api'
import { DAY_LABELS, PREFERENCE_LABELS, PREFERENCES } from '@/lib/format'
import type { PlaceSearchResult, Preference } from '@/lib/types'
import { Wordmark } from '../app-header'
import { PlaceSearch } from '../place-search'
import { Button } from '../primitives/button'
import { ChoiceChip } from '../primitives/chip'
import { TimeField } from '../primitives/controls'
import { Segmented } from '../primitives/segmented'
import { Text, textStyle } from '../primitives/text'

type Step = 'welcome' | 'home' | 'work' | 'routine'
const STEPS: Step[] = ['home', 'work', 'routine']

function Progress({ step }: { step: Step }) {
  const i = STEPS.indexOf(step)
  return (
    <div className="flex items-center gap-1.5" aria-label={`Step ${i + 1} of ${STEPS.length}`} role="img">
      {STEPS.map((s, j) => (
        <span key={s} className={`h-1.5 flex-1 rounded-full ${j <= i ? 'bg-px-brand' : 'bg-px-border'}`} />
      ))}
    </div>
  )
}

function Welcome({ onStart, name, setName, busy, error }: {
  onStart: () => void
  name: string
  setName: (v: string) => void
  busy: boolean
  error: string | null
}) {
  const points = [
    { icon: Gauge, text: 'Learns your normal Home → Work and Work → Home trips.' },
    { icon: BellRing, text: 'Tells you before you leave when today isn’t normal — and what to take instead.' },
    { icon: ShieldCheck, text: 'No account details, no background location.' },
  ]
  return (
    <div className="flex flex-1 flex-col gap-8 pt-10">
      <div className="flex flex-col gap-4">
        <Wordmark size={36} />
        <Text variant="display" as="h1" className="text-balance">
          Know when your normal commute is not normal.
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
      <div className="flex flex-col gap-2">
        <label htmlFor="ob-name">
          <Text variant="subhead" as="span" tone="secondary">
            What should we call you? <span className="text-px-text-tertiary">(optional)</span>
          </Text>
        </label>
        <input
          id="ob-name"
          autoComplete="given-name"
          value={name}
          maxLength={40}
          onChange={(e) => setName(e.target.value)}
          placeholder="First name"
          className="h-14 w-full rounded-px-md border border-px-border-strong bg-px-surface px-4 text-px-text placeholder:text-px-text-tertiary"
          style={textStyle('body')}
        />
      </div>
      <div className="mt-auto flex flex-col gap-2 pb-4">
        {error && (
          <Text variant="footnote" tone="attention" role="alert">
            {error}
          </Text>
        )}
        <Button block onClick={onStart} loading={busy}>
          Get started
        </Button>
      </div>
    </div>
  )
}

export function OnboardingScreen({ onStart, onDone }: { onStart: () => void; onDone: () => void }) {
  const [step, setStep] = useState<Step>(() => (tokenStore.get() ? 'home' : 'welcome'))
  const [name, setName] = useState('')
  const [home, setHome] = useState<PlaceSearchResult | null>(null)
  const [work, setWork] = useState<PlaceSearchResult | null>(null)
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
      setStep('home')
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
        name: name.trim() || undefined,
        home: { label: 'home', name: home.name, lat: home.lat, lon: home.lon, source: 'manual' },
        work: { label: 'work', name: work.name, lat: work.lat, lon: work.lon, source: 'manual' },
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

  const back = () => setStep(step === 'routine' ? 'work' : step === 'work' ? 'home' : 'home')
  const invalidRoutine = days.length === 0 || mStart >= mEnd || eStart >= eEnd

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-[430px] flex-col bg-px-canvas px-5 pb-safe pt-safe">
      {step === 'welcome' ? (
        <Welcome onStart={start} name={name} setName={setName} busy={busy} error={error} />
      ) : (
        <div className="flex flex-1 flex-col gap-6 pt-4">
          <div className="flex items-center gap-3">
            {step !== 'home' ? (
              <button
                type="button"
                onClick={back}
                aria-label="Back"
                className="-ml-2 flex size-11 items-center justify-center rounded-full text-px-text hover:bg-px-surface-sunken"
              >
                <ArrowLeft className="size-5" aria-hidden />
              </button>
            ) : (
              <span className="size-11 -ml-2 flex items-center">
                <Wordmark size={20} />
              </span>
            )}
            <div className="flex-1">
              <Progress step={step} />
            </div>
          </div>

          {step === 'home' && (
            <section className="flex flex-col gap-5" aria-labelledby="ob-home">
              <div className="flex flex-col gap-2">
                <Text variant="title1" as="h1" id="ob-home">
                  Where&apos;s home?
                </Text>
                <Text variant="callout" tone="secondary" className="text-pretty">
                  Paxen only stores your places to ~10 m precision. You can edit or delete them any time.
                </Text>
              </div>
              <PlaceSearch label="Search for home" placeholder="Station, street or postcode" selected={home} onSelect={setHome} autoFocus />
            </section>
          )}

          {step === 'work' && (
            <section className="flex flex-col gap-5" aria-labelledby="ob-work">
              <div className="flex flex-col gap-2">
                <Text variant="title1" as="h1" id="ob-work">
                  And where do you work?
                </Text>
                <Text variant="callout" tone="secondary" className="text-pretty">
                  Paxen only stores your places to ~10 m precision. You can edit or delete them any time.
                </Text>
              </div>
              <PlaceSearch label="Search for work" placeholder="Station, street or postcode" selected={work} onSelect={setWork} autoFocus />
            </section>
          )}

          {step === 'routine' && (
            <section className="flex flex-col gap-6" aria-labelledby="ob-routine">
              <div className="flex flex-col gap-2">
                <Text variant="title1" as="h1" id="ob-routine">
                  Your routine
                </Text>
                <Text variant="callout" tone="secondary" className="text-pretty">
                  No background location needed — we use your schedule.
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
                    Morning · leave home between
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
                    Evening · leave work between
                  </Text>
                </legend>
                <div className="flex gap-3">
                  <TimeField label="From" value={eStart} onChange={setEStart} />
                  <TimeField label="To" value={eEnd} onChange={setEEnd} />
                </div>
              </fieldset>
              <div className="flex flex-col gap-2">
                <Text variant="subhead" tone="secondary">
                  Route preference
                </Text>
                <Segmented
                  label="Route preference"
                  value={pref}
                  scroll
                  options={PREFERENCES.map((p) => ({ value: p, label: PREFERENCE_LABELS[p] }))}
                  onChange={setPref}
                />
              </div>
              {invalidRoutine && (
                <Text variant="footnote" tone="watch">
                  Pick at least one day, and make each window end after it starts.
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
            {step === 'home' && (
              <Button block disabled={!home} onClick={() => setStep('work')}>
                Continue
              </Button>
            )}
            {step === 'work' && (
              <Button block disabled={!work} onClick={() => setStep('routine')}>
                Continue
              </Button>
            )}
            {step === 'routine' && (
              <Button block disabled={invalidRoutine} loading={busy} onClick={submit}>
                Start monitoring
              </Button>
            )}
          </div>
        </div>
      )}
    </main>
  )
}
