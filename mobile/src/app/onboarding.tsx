import { useState } from 'react'
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, View } from 'react-native'
import { router } from 'expo-router'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import { ArrowLeft, BellRing, Gauge, ShieldCheck } from 'lucide-react-native'
import { PREFERENCE_LABELS, PREFERENCES } from '@/shared/format'
import { layout } from '@/shared/paxen-tokens'
import type { ChosenStop, PlaceSearchResult, Preference } from '@/shared/types'
import { api, tokenStore } from '@/lib/api'
import { revalidateAll, useToken } from '@/lib/hooks'
import { usePalette } from '@/lib/theme'
import { TimeField } from '@/components/controls'
import { PlaceSearch, StopPicker } from '@/components/places'
import { Text } from '@/components/text'
import { Wordmark } from '@/components/transit'
import { Button, ErrorText, Segmented } from '@/components/ui'
import { DayPicker } from '@/components/you'

type Step = 'welcome' | 'places' | 'routine'
const STEPS: Step[] = ['places', 'routine']

function Progress({ step }: { step: Step }) {
  const p = usePalette()
  const i = STEPS.indexOf(step)
  return (
    <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12 }}>
      <View style={{ flex: 1, flexDirection: 'row', gap: 6 }}>
        {STEPS.map((s, j) => (
          <View key={s} style={{ flex: 1, height: 6, borderRadius: 3, backgroundColor: j <= i ? p.brand : p.border }} />
        ))}
      </View>
      <Text variant="footnote" tone="secondary" tabular>
        Step {i + 1} of {STEPS.length}
      </Text>
    </View>
  )
}

function Welcome({ onStart, busy, error }: { onStart: () => void; busy: boolean; error: string | null }) {
  const p = usePalette()
  const points = [
    { icon: Gauge, text: 'Learns your usual trip to work and back.' },
    { icon: BellRing, text: 'Tells you before you leave if today is different, and what to take instead.' },
    { icon: ShieldCheck, text: 'No account to create, and your location is never stored.' },
  ]
  return (
    <View style={{ flex: 1, gap: 32, paddingTop: 40 }}>
      <View style={{ gap: 16 }}>
        <Wordmark size={36} />
        <Text variant="display" accessibilityRole="header">
          Know before you leave if your commute is off.
        </Text>
      </View>
      <View style={{ gap: 16 }}>
        {points.map(({ icon: Icon, text }) => (
          <View key={text} style={{ flexDirection: 'row', gap: 12 }}>
            <View style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: p.brandSoft, alignItems: 'center', justifyContent: 'center' }}>
              <Icon size={20} color={p.onBrandSoft} />
            </View>
            <Text variant="callout" tone="secondary" style={{ flex: 1, paddingTop: 6 }}>
              {text}
            </Text>
          </View>
        ))}
      </View>
      <View style={{ marginTop: 'auto', gap: 8, paddingBottom: 16 }}>
        <ErrorText>{error}</ErrorText>
        <Button block onPress={onStart} loading={busy}>
          Get started
        </Button>
        <Text variant="footnote" tone="secondary" style={{ textAlign: 'center' }}>
          Takes about a minute.
        </Text>
      </View>
    </View>
  )
}

export default function Onboarding() {
  const p = usePalette()
  const insets = useSafeAreaInsets()
  const token = useToken()
  const [step, setStep] = useState<Step>(() => (token ? 'places' : 'welcome'))
  const [home, setHomePlace] = useState<PlaceSearchResult | null>(null)
  const [work, setWorkPlace] = useState<PlaceSearchResult | null>(null)
  const [homeStops, setHomeStops] = useState<ChosenStop[]>([])
  const [workStops, setWorkStops] = useState<ChosenStop[]>([])
  const [days, setDays] = useState([0, 1, 2, 3, 4])
  const [mStart, setMStart] = useState('08:00')
  const [mEnd, setMEnd] = useState('08:45')
  const [eStart, setEStart] = useState('17:30')
  const [eEnd, setEEnd] = useState('18:15')
  const [pref, setPref] = useState<Preference>('balanced')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // A different place means a different set of nearby stations.
  const setHome = (r: PlaceSearchResult) => {
    setHomePlace(r)
    setHomeStops([])
  }
  const setWork = (r: PlaceSearchResult) => {
    setWorkPlace(r)
    setWorkStops([])
  }

  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      if (!tokenStore.get()) {
        const { token: t } = await api.createUser()
        tokenStore.set(t)
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
      await revalidateAll()
      router.replace('/')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save your routine.')
    } finally {
      setBusy(false)
    }
  }

  const invalidRoutine = days.length === 0 || mStart >= mEnd || eStart >= eEnd

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, backgroundColor: p.canvas }}>
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ flexGrow: 1, paddingHorizontal: layout.gutter, paddingTop: insets.top + 8, paddingBottom: insets.bottom + 8 }}
      >
        {step === 'welcome' ? (
          <Welcome onStart={start} busy={busy} error={error} />
        ) : (
          <View style={{ flex: 1, gap: 24, paddingTop: 8 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
              {step === 'routine' ? (
                <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={() => setStep('places')} hitSlop={8} style={{ width: 44, height: 44, marginLeft: -8, alignItems: 'center', justifyContent: 'center' }}>
                  <ArrowLeft size={20} color={p.text} />
                </Pressable>
              ) : (
                <View style={{ height: 44, justifyContent: 'center' }}>
                  <Wordmark size={20} />
                </View>
              )}
              <Progress step={step} />
            </View>

            {step === 'places' && (
              <View style={{ gap: 24 }}>
                <View style={{ gap: 8 }}>
                  <Text variant="title1" accessibilityRole="header">
                    Where do you commute?
                  </Text>
                  <Text variant="callout" tone="secondary">
                    A station name or postcode is enough. You can change this later.
                  </Text>
                </View>
                <View style={{ gap: 16 }}>
                  <PlaceSearch label="Home" placeholder="Home: station or postcode" selected={home} onSelect={setHome} autoFocus />
                  {home && <StopPicker lat={home.lat} lon={home.lon} value={homeStops} onChange={setHomeStops} placeLabel="home" />}
                </View>
                {home && (
                  <View style={{ gap: 16 }}>
                    <PlaceSearch label="Work" placeholder="Work: station or postcode" selected={work} onSelect={setWork} />
                    {work && <StopPicker lat={work.lat} lon={work.lon} value={workStops} onChange={setWorkStops} placeLabel="work" />}
                  </View>
                )}
              </View>
            )}

            {step === 'routine' && (
              <View style={{ gap: 24 }}>
                <View style={{ gap: 8 }}>
                  <Text variant="title1" accessibilityRole="header">
                    Your routine
                  </Text>
                  <Text variant="callout" tone="secondary">
                    We&apos;ve filled in a typical commute. Change anything that&apos;s off.
                  </Text>
                </View>
                <View style={{ gap: 8 }}>
                  <Text variant="subhead" tone="secondary">
                    Days you commute
                  </Text>
                  <DayPicker days={days} onChange={setDays} />
                </View>
                <View style={{ gap: 8 }}>
                  <Text variant="subhead" tone="secondary">
                    Morning: leave home between
                  </Text>
                  <View style={{ flexDirection: 'row', gap: 12 }}>
                    <TimeField label="From" value={mStart} onChange={setMStart} />
                    <TimeField label="To" value={mEnd} onChange={setMEnd} />
                  </View>
                </View>
                <View style={{ gap: 8 }}>
                  <Text variant="subhead" tone="secondary">
                    Evening: leave work between
                  </Text>
                  <View style={{ flexDirection: 'row', gap: 12 }}>
                    <TimeField label="From" value={eStart} onChange={setEStart} />
                    <TimeField label="To" value={eEnd} onChange={setEEnd} />
                  </View>
                </View>
                <View style={{ gap: 8 }}>
                  <Text variant="subhead" tone="secondary">
                    What matters most?
                  </Text>
                  <Segmented label="What matters most" value={pref} scroll options={PREFERENCES.map((v) => ({ value: v, label: PREFERENCE_LABELS[v] }))} onChange={setPref} />
                </View>
                {invalidRoutine && (
                  <Text variant="footnote" tone="watch">
                    Pick at least one day, and make sure each window ends after it starts.
                  </Text>
                )}
              </View>
            )}

            <View style={{ marginTop: 'auto', gap: 8, paddingTop: 16, paddingBottom: 8 }}>
              <ErrorText>{error}</ErrorText>
              {step === 'places' && (
                <Button block disabled={!home || !work} onPress={() => setStep('routine')}>
                  Continue
                </Button>
              )}
              {step === 'routine' && (
                <Button block disabled={invalidRoutine} loading={busy} onPress={submit}>
                  Done, show my commute
                </Button>
              )}
            </View>
          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  )
}
