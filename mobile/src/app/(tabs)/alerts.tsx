import { useEffect, useRef, useState } from 'react'
import { Pressable, View } from 'react-native'
import { BellOff, Target, ThumbsDown, ThumbsUp } from 'lucide-react-native'
import { mutate as globalMutate } from 'swr'
import { fmtAgo } from '@/shared/format'
import { radii } from '@/shared/paxen-tokens'
import { CONFIDENCE_PLAIN } from '@/shared/plain'
import type { Alert } from '@/shared/types'
import { api } from '@/lib/api'
import { useAlerts } from '@/lib/hooks'
import { alpha, usePalette } from '@/lib/theme'
import { Screen } from '@/components/screen'
import { Text } from '@/components/text'
import { Card, EmptyState, ErrorState, ErrorText, Skeleton } from '@/components/ui'

type Feedback = NonNullable<Alert['feedback']>

const FEEDBACK: { value: Feedback; label: string; icon: typeof ThumbsUp }[] = [
  { value: 'useful', label: 'Useful', icon: ThumbsUp },
  { value: 'not_useful', label: 'Not useful', icon: ThumbsDown },
  { value: 'inaccurate', label: 'Wrong', icon: Target },
]

function AlertCard({ alert, onFeedback }: { alert: Alert; onFeedback: (f: Feedback) => Promise<void> }) {
  const p = usePalette()
  const [pending, setPending] = useState<Feedback | null>(null)
  const [failed, setFailed] = useState(false)
  const send = async (f: Feedback) => {
    setPending(f)
    setFailed(false)
    try {
      await onFeedback(f)
    } catch {
      setFailed(true)
    } finally {
      setPending(null)
    }
  }
  return (
    <Card style={[{ padding: 16, gap: 12 }, !alert.read ? { borderWidth: 1, borderColor: alpha(p.attention, 0.4) } : null]}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <View style={{ width: 24, height: 24, borderRadius: 6, backgroundColor: p.brand, alignItems: 'center', justifyContent: 'center' }}>
            <Text color={p.onBrand} style={{ fontSize: 14, lineHeight: 16, fontWeight: '800' }}>
              p
            </Text>
          </View>
          <Text variant="caption" tone="secondary">
            Paxen
          </Text>
        </View>
        <Text variant="caption" tone="secondary">
          {fmtAgo(alert.created_at)}
        </Text>
      </View>
      <View style={{ gap: 4 }}>
        <Text variant="headline" tone={alert.kind === 'usual_unavailable' ? 'attention' : 'primary'}>
          {alert.title}
        </Text>
        <Text variant="callout">{alert.body}</Text>
        <Text variant="footnote" tone="secondary">
          {CONFIDENCE_PLAIN[alert.confidence].label}
        </Text>
      </View>
      <View accessibilityLabel="Was this alert helpful?" style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
        {FEEDBACK.map(({ value, label, icon: Icon }) => {
          const sel = alert.feedback === value
          const fg = sel ? p.onAccent : p.text
          return (
            <Pressable
              key={value}
              accessibilityRole="button"
              accessibilityState={{ selected: sel, disabled: pending !== null }}
              disabled={pending !== null}
              onPress={() => send(value)}
              style={{
                height: 44,
                paddingHorizontal: 16,
                borderRadius: radii.pill,
                borderWidth: 1,
                borderColor: sel ? p.accent : p.borderStrong,
                backgroundColor: sel ? p.accent : p.surface,
                flexDirection: 'row',
                alignItems: 'center',
                gap: 6,
                opacity: pending !== null ? 0.6 : 1,
              }}
            >
              <Icon size={16} color={fg} />
              <Text color={fg} style={{ fontSize: 14, fontWeight: '600' }}>
                {label}
              </Text>
            </Pressable>
          )
        })}
      </View>
      {failed && <ErrorText>Couldn&apos;t send feedback. Try again.</ErrorText>}
    </Card>
  )
}

export default function AlertsScreen() {
  const { data, error, isLoading, mutate } = useAlerts()
  const marked = useRef(false)

  useEffect(() => {
    if (marked.current || !data?.some((a) => !a.read)) return
    marked.current = true
    api
      .markAlertsRead()
      .then(() => globalMutate(['dashboard']))
      .catch(() => {
        marked.current = false
      })
  }, [data])

  const feedback = async (id: string, f: Feedback) => {
    await api.alertFeedback(id, f)
    await mutate((list) => list?.map((a) => (a.id === id ? { ...a, feedback: f } : a)), { revalidate: false })
  }

  return (
    <Screen title="Alerts" gap={20} onRefresh={() => mutate()}>
      {error && !data ? (
        <ErrorState error={error} onRetry={() => mutate()} />
      ) : isLoading || !data ? (
        [0, 1].map((i) => <Skeleton key={i} style={{ height: 176, borderRadius: 20 }} />)
      ) : data.length === 0 ? (
        <EmptyState
          icon={(c) => <BellOff size={24} color={c} />}
          title="Nothing to report"
          body="We'll only message you when your usual route is slower than normal or you're likely to be late. You can change this in You → Alerts."
        />
      ) : (
        <View style={{ gap: 12 }}>
          {data.map((a) => (
            <AlertCard key={a.id} alert={a} onFeedback={(f) => feedback(a.id, f)} />
          ))}
        </View>
      )}
    </Screen>
  )
}
