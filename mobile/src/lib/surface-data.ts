/**
 * What the lock-screen trip and the home-screen widget show, worked out from API data. Pure (no imports), so it
 * can be tested in Node; the native side is lib/native-surfaces.ios.ts.
 */
export interface ActivityProps {
  status: string
  summary: string
  eta: number | null
  headline: string
  next: string | null
  nextAt: number | null
  note: string | null
}

interface LiveLike {
  status: string
  summary: string | null
  eta?: string
  phase?: 'walking' | 'waiting' | 'on_board'
  current_leg?: number
  legs: { line_name: string | null; from: string; to: string }[]
  next_departure?: { line_name: string | null; stop: string; catch_index?: number | null; trains?: { at: string }[] } | null
  disruptions?: { line_name: string; description: string }[]
}

const ms = (iso: string | null | undefined) => (iso ? new Date(iso).getTime() : null)

/** The same shape the server pushes (backend paxen/activity.py props()). */
export function activityProps(live: LiveLike): ActivityProps {
  const summary = live.summary ?? ''
  if (live.status !== 'active')
    return { status: live.status, summary, eta: null, headline: live.status === 'arrived' ? 'You\u2019ve arrived' : 'Trip finished', next: null, nextAt: null, note: null }
  const leg = live.legs[live.current_leg ?? 0]
  const line = leg?.line_name ?? 'service'
  const headline =
    live.phase === 'walking' ? `Walk to ${leg?.to ?? ''}` : live.phase === 'waiting' ? `Wait for the ${line} at ${leg?.from ?? ''}` : `On the ${line} to ${leg?.to ?? ''}`
  const nd = live.next_departure
  const next = nd && live.phase !== 'on_board' ? `${nd.line_name ?? 'Next service'} from ${nd.stop}` : null
  const train = nd?.catch_index != null ? nd.trains?.[nd.catch_index] : undefined
  const dis = live.disruptions?.[0]
  return {
    status: 'active',
    summary,
    eta: ms(live.eta),
    headline: headline.trim(),
    next,
    nextAt: next && train ? ms(train.at) : null,
    note: dis ? `${dis.line_name}: ${dis.description}` : null,
  }
}

export interface WidgetProps {
  title: string
  tone: 'good' | 'slower' | 'disrupted' | 'none'
  statusLabel: string
  leaveLabel: string
  leaveAt: number | null
  leaveText: string | null
  arriveAt: number | null
  route: string
  stale: boolean
  usual: string | null
}

interface EvaluationLike {
  commute: { id: string; name: string }
  status: string
  delta_min: number | null
  baseline: { p50: number | null }
  recommended: { summary: string; depart_at: string; arrive_at: string; leave_by?: { at: string } | null } | null
}

/** Live times go stale: after this the widget falls back to the usual journey time. */
export const WIDGET_FRESH_MS = 20 * 60_000

/** Timeline for the widget: the live answer now, then a plain "usual time" card once it has aged. */
export function widgetEntries(d: { generated_at: string; active_commute_id: string | null; commutes: EvaluationLike[] }): { at: number; props: WidgetProps }[] {
  const ev = d.commutes.find((c) => c.commute.id === d.active_commute_id) ?? d.commutes[0]
  if (!ev) return []
  const at = new Date(d.generated_at).getTime()
  const rec = ev.recommended
  const usual = ev.baseline.p50 != null ? `Usually ${Math.round(ev.baseline.p50)} min` : null
  const slower = ev.delta_min != null && Math.round(ev.delta_min) > 0 ? Math.round(ev.delta_min) : null
  const tone: WidgetProps['tone'] = ev.status === 'disrupted' ? 'disrupted' : ev.status === 'slower' ? 'slower' : ev.status === 'unknown' || !rec ? 'none' : 'good'
  const statusLabel =
    ev.status === 'disrupted' ? 'Usual route not running' : slower != null && ev.status === 'slower' ? `${slower} min slower` : !rec ? 'No route right now' : 'All good'
  const depart = rec ? new Date(rec.depart_at).getTime() : null
  const later = depart != null && depart - at > 90_000 // the commute hasn't started: its start time
  const leaveAt = rec?.leave_by ? new Date(rec.leave_by.at).getTime() : later ? depart : null
  const live: WidgetProps = {
    title: ev.commute.name,
    tone,
    statusLabel,
    leaveLabel: leaveAt != null ? 'Leave by' : 'Leave',
    leaveAt,
    leaveText: leaveAt != null ? null : rec ? 'Now' : '',
    arriveAt: rec ? new Date(rec.arrive_at).getTime() : null,
    route: rec?.summary ?? '',
    stale: false,
    usual,
  }
  // A forecast for a commute that starts later holds until then; one for right now ages in minutes.
  const until = later && depart != null ? Math.max(depart, at + WIDGET_FRESH_MS) : at + WIDGET_FRESH_MS
  return [
    { at, props: live },
    { at: until, props: { ...live, stale: true, tone: 'none', leaveAt: null, leaveText: null, arriveAt: null } },
  ]
}
