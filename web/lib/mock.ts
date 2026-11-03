/**
 * In-memory demo backend. Serves the captured fixtures in lib/fixtures so the app is
 * fully clickable without NEXT_PUBLIC_PAXEN_API_URL. State resets on reload.
 */
import alertsFixture from './fixtures/alerts.json'
import dashboardFixture from './fixtures/dashboard.json'
import insightsFixture from './fixtures/insights.json'
import networkFixture from './fixtures/network-status.json'
import { ApiError, type NetworkStatusResponse, type OnboardingIn, type StartTripIn } from './api'
import type {
  Alert,
  Commute,
  CommuteEvaluation,
  Dashboard,
  Insights,
  Place,
  PlaceSearchResult,
  Preference,
  RouteOption,
  Trip,
  User,
} from './types'

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v))
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

const SCENARIOS = ['auto', 'normal', 'victoria-severe', 'victoria-suspended', 'central-minor', 'weaver-suspended', 'mixed']

const SEARCH_INDEX: PlaceSearchResult[] = [
  { name: 'Orford Road, Walthamstow', lat: 51.5835, lon: -0.0172, kind: 'address', stop_id: null, detail: 'London E17' },
  { name: 'Walthamstow Central', lat: 51.583, lon: -0.0199, kind: 'station', stop_id: 'walthamstow-central', detail: 'Victoria · Weaver line' },
  { name: 'Regent Street office', lat: 51.5151, lon: -0.1418, kind: 'address', stop_id: null, detail: 'Regent Street, London W1' },
  { name: 'Oxford Circus', lat: 51.5152, lon: -0.1415, kind: 'station', stop_id: 'oxford-circus', detail: 'Victoria · Central · Bakerloo' },
  { name: 'Liverpool Street', lat: 51.5178, lon: -0.0823, kind: 'station', stop_id: 'liverpool-street', detail: 'Central · Elizabeth line · Weaver line' },
  { name: 'Bond Street', lat: 51.5142, lon: -0.1494, kind: 'station', stop_id: 'bond-street', detail: 'Central · Jubilee · Elizabeth line' },
  { name: 'Hoe Street, Walthamstow', lat: 51.5862, lon: -0.0141, kind: 'address', stop_id: null, detail: 'London E17' },
  { name: 'Blackhorse Road', lat: 51.5867, lon: -0.0411, kind: 'station', stop_id: 'blackhorse-road', detail: 'Victoria · Suffragette line' },
  { name: 'Canary Wharf', lat: 51.5054, lon: -0.0235, kind: 'station', stop_id: 'canary-wharf', detail: 'Jubilee · Elizabeth line · DLR' },
  { name: 'Stratford', lat: 51.5416, lon: -0.0034, kind: 'station', stop_id: 'stratford', detail: 'Central · Elizabeth line · Jubilee' },
]

function createState() {
  const dashboard = clone(dashboardFixture) as unknown as Dashboard
  const onRoutes = new Set(dashboard.network.filter((l) => l.on_my_routes).map((l) => l.line_id))
  const network = clone(networkFixture) as unknown as NetworkStatusResponse
  network.lines = network.lines.map((l) => ({ ...l, on_my_routes: onRoutes.has(l.line_id) }))
  network.lines.sort((a, b) => Number(b.on_my_routes) - Number(a.on_my_routes))
  return {
    dashboard,
    network,
    alerts: clone(alertsFixture) as unknown as Alert[],
    insights: clone(insightsFixture) as unknown as Insights,
    trips: [] as Trip[],
    scenario: 'victoria-severe',
  }
}

let state = createState()

const places = (): Place[] => {
  const map = new Map<string, Place>()
  for (const e of state.dashboard.commutes) {
    map.set(e.commute.origin.id, e.commute.origin)
    map.set(e.commute.dest.id, e.commute.dest)
  }
  return [...map.values()]
}

const findEval = (id: string) => {
  const ev = state.dashboard.commutes.find((c) => c.commute.id === id)
  if (!ev) throw new ApiError(404, 'Commute not found')
  return ev
}

const updateCommute = (id: string, patch: Partial<Commute>) => {
  const ev = findEval(id)
  ev.commute = { ...ev.commute, ...patch }
  if (patch.preference) ev.preference = patch.preference
  return ev.commute
}

function rank(options: RouteOption[], pref: Preference): RouteOption[] {
  const feasibleFirst = (a: RouteOption, b: RouteOption) => Number(b.feasible) - Number(a.feasible)
  const by: Record<Preference, (a: RouteOption, b: RouteOption) => number> = {
    balanced: () => 0,
    fastest: (a, b) => a.duration.p50 - b.duration.p50,
    reliable: (a, b) => b.on_time_chance - a.on_time_chance || a.duration.p90 - b.duration.p90,
    least_walking: (a, b) => a.walking_min - b.walking_min,
    fewest_changes: (a, b) => a.changes - b.changes || a.duration.p50 - b.duration.p50,
  }
  return [...options].sort((a, b) => feasibleFirst(a, b) || by[pref](a, b))
}

const id = () => Math.random().toString(16).slice(2) + Date.now().toString(16)

export async function mockRequest(method: string, fullPath: string, body: unknown, token: string | null) {
  await sleep(fullPath.includes('/dev/seed') ? 4000 : 220)
  const [path, qs] = fullPath.split('?')
  const query = new URLSearchParams(qs ?? '')
  const route = `${method} ${path}`

  if (route === 'POST /v1/users') {
    state = createState()
    return { user_id: state.dashboard.user.id, token: `demo-${id()}` }
  }
  if (!token) throw new ApiError(401, 'Not signed in')

  const d = state.dashboard
  d.unread_alerts = state.alerts.filter((a) => !a.read).length

  switch (route) {
    case 'GET /v1/me':
      return d.user
    case 'PATCH /v1/me':
      d.user = { ...d.user, ...(body as Partial<User>) }
      return d.user
    case 'DELETE /v1/me':
      state = createState()
      return { ok: true }
    case 'DELETE /v1/me/history': {
      const res = { trips_deleted: state.trips.length, alerts_deleted: state.alerts.length }
      state.trips = []
      state.alerts = []
      state.insights.personal = { ...state.insights.personal, trips: 0, alerts: 0, alerts_rated: 0, alerts_rated_useful: 0, alerts_followed: 0, minutes_saved: 0, interval_hit_rate: null, journey_forecast_mae_min: null }
      return res
    }
    case 'POST /v1/onboarding': {
      const b = body as OnboardingIn
      if (b.name) d.user.name = b.name
      for (const ev of d.commutes) {
        ev.commute.days = b.days
        ev.commute.preference = b.preference
        ev.preference = b.preference
        const w = ev.commute.name === 'Home' ? b.evening : b.morning
        ev.commute.window_start = w.start
        ev.commute.window_end = w.end
        for (const key of ['origin', 'dest'] as const) {
          const src = ev.commute[key].label === 'home' ? b.home : ev.commute[key].label === 'work' ? b.work : null
          if (src) ev.commute[key] = { ...ev.commute[key], name: src.name, lat: src.lat, lon: src.lon, source: src.source }
        }
      }
      return { ok: true }
    }
    case 'GET /v1/places/search': {
      const q = (query.get('q') ?? '').trim().toLowerCase()
      if (q.length < 2) return []
      return SEARCH_INDEX.filter((p) => `${p.name} ${p.detail ?? ''}`.toLowerCase().includes(q)).slice(0, 8)
    }
    case 'GET /v1/places':
      return places()
    case 'GET /v1/commutes':
      return d.commutes.map((c) => c.commute)
    case 'GET /v1/dashboard':
      return { ...d, generated_at: new Date().toISOString() }
    case 'GET /v1/network/status':
      return { ...state.network, generated_at: new Date().toISOString() }
    case 'GET /v1/trips':
      return state.trips
    case 'POST /v1/trips': {
      const b = body as StartTripIn
      const trip: Trip = {
        id: id(),
        commute_id: b.commute_id,
        summary: b.summary,
        signature: b.signature,
        route_key: b.signature,
        started_at: new Date().toISOString(),
        arrived_at: null,
        duration_min: null,
        forecast: { p10: b.forecast_p10, p50: b.forecast_p50, p90: b.forecast_p90 },
        followed_alert_id: b.followed_alert_id ?? null,
        source: 'app',
      }
      state.trips.unshift(trip)
      return trip
    }
    case 'GET /v1/alerts':
      return state.alerts
    case 'POST /v1/alerts/read':
      state.alerts.forEach((a) => (a.read = true))
      return { ok: true }
    case 'GET /v1/insights':
      return state.insights
    case 'GET /v1/dev/scenarios':
      return { scenarios: SCENARIOS, current: state.scenario }
    case 'POST /v1/dev/scenario':
      state.scenario = String((body as { scenario: string }).scenario)
      return { ok: true, scenario: state.scenario }
    case 'POST /v1/dev/check-now':
    case 'POST /v1/dev/seed':
      return { ok: true }
  }

  let m: RegExpMatchArray | null
  if ((m = path.match(/^\/v1\/places\/([^/]+)$/))) {
    const pid = m[1]
    if (method === 'PATCH') {
      const patch = body as Partial<Place>
      let updated: Place | null = null
      for (const ev of d.commutes) {
        for (const key of ['origin', 'dest'] as const) {
          if (ev.commute[key].id === pid) {
            ev.commute[key] = { ...ev.commute[key], ...patch, id: pid }
            updated = ev.commute[key]
          }
        }
      }
      if (!updated) throw new ApiError(404, 'Place not found')
      return updated
    }
    if (method === 'DELETE') {
      d.commutes = d.commutes.filter((ev) => ev.commute.origin.id !== pid && ev.commute.dest.id !== pid)
      if (!d.commutes.some((c) => c.commute.id === d.active_commute_id)) d.active_commute_id = d.commutes[0]?.commute.id ?? null
      return { ok: true }
    }
  }
  if ((m = path.match(/^\/v1\/commutes\/([^/]+)$/)) && method === 'PATCH') {
    return updateCommute(m[1], body as Partial<Commute>)
  }
  if ((m = path.match(/^\/v1\/commutes\/([^/]+)\/compare$/)) && method === 'GET') {
    const ev = findEval(m[1])
    const pref = (query.get('preference') as Preference | null) ?? ev.preference
    const result: CommuteEvaluation = { ...clone(ev), preference: pref }
    result.options = rank(result.options, pref)
    return result
  }
  if ((m = path.match(/^\/v1\/commutes\/([^/]+)\/usual$/)) && method === 'PUT') {
    const ev = findEval(m[1])
    const sig = (body as { signature: string }).signature
    const opt = ev.options.find((o) => o.id === sig)
    if (!opt) throw new ApiError(404, 'Route not found')
    ev.options = ev.options.map((o) => ({ ...o, is_usual: o.id === sig }))
    ev.usual = ev.options.find((o) => o.id === sig) ?? null
    return updateCommute(ev.commute.id, { usual_signature: sig, usual_summary: opt.summary })
  }
  if ((m = path.match(/^\/v1\/trips\/([^/]+)\/arrive$/)) && method === 'POST') {
    const trip = state.trips.find((t) => t.id === m![1])
    if (!trip) throw new ApiError(404, 'Trip not found')
    trip.arrived_at = new Date().toISOString()
    trip.duration_min = (new Date(trip.arrived_at).getTime() - new Date(trip.started_at).getTime()) / 60000
    state.insights.personal.trips += 1
    return trip
  }
  if ((m = path.match(/^\/v1\/alerts\/([^/]+)\/feedback$/)) && method === 'POST') {
    const alert = state.alerts.find((a) => a.id === m![1])
    if (!alert) throw new ApiError(404, 'Alert not found')
    alert.feedback = (body as { feedback: Alert['feedback'] }).feedback
    const rated = state.alerts.filter((a) => a.feedback)
    state.insights.personal.alerts_rated = rated.length
    state.insights.personal.alerts_rated_useful = rated.filter((a) => a.feedback === 'useful').length
    return alert
  }

  throw new ApiError(404, `Demo backend has no handler for ${route}`)
}
