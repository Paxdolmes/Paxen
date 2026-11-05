import type {
  Alert,
  LiveTrip,
  ChosenStop,
  NearbyStop,
  Commute,
  CommuteEvaluation,
  Dashboard,
  FeedHealth,
  Insights,
  LineStatus,
  Place,
  PlaceSearchResult,
  Preference,
  Trip,
  User,
} from './types'

export const API_BASE = (process.env.NEXT_PUBLIC_PAXEN_API_URL ?? '').replace(/\/+$/, '')
export const IS_DEMO = API_BASE === ''

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/* ---------- token store (localStorage + subscribers) ---------- */

const TOKEN_KEY = 'paxen.token'
const listeners = new Set<() => void>()

export const tokenStore = {
  get(): string | null {
    if (typeof window === 'undefined') return null
    try {
      return window.localStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set(token: string) {
    window.localStorage.setItem(TOKEN_KEY, token)
    listeners.forEach((l) => l())
  },
  clear() {
    try {
      window.localStorage.removeItem(TOKEN_KEY)
    } catch {}
    listeners.forEach((l) => l())
  },
  subscribe(cb: () => void) {
    listeners.add(cb)
    const onStorage = (e: StorageEvent) => e.key === TOKEN_KEY && cb()
    window.addEventListener('storage', onStorage)
    return () => {
      listeners.delete(cb)
      window.removeEventListener('storage', onStorage)
    }
  },
}

/* ---------- transport ---------- */

type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const token = tokenStore.get()

  if (IS_DEMO) {
    const { mockRequest } = await import('./mock')
    try {
      return (await mockRequest(method, path, body, token)) as T
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) tokenStore.clear()
      throw e
    }
  }

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, "Can't reach Paxen right now. Check your connection.")
  }

  if (res.status === 401) {
    tokenStore.clear()
    throw new ApiError(401, 'Your session has ended. Let’s set you up again.')
  }
  if (!res.ok) {
    let message = `Something went wrong (${res.status}).`
    try {
      const data = await res.json()
      if (typeof data?.detail === 'string') message = data.detail
      else if (typeof data?.error === 'string') message = data.error
    } catch {}
    throw new ApiError(res.status, message)
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/* ---------- endpoints ---------- */

export interface PlaceIn {
  label: 'home' | 'work'
  name: string
  lat: number
  lon: number
  source: Place['source']
  stops?: ChosenStop[]
}

export interface OnboardingIn {
  name?: string
  home: PlaceIn
  work: PlaceIn
  days: number[]
  morning: { start: string; end: string }
  evening: { start: string; end: string }
  preference: Preference
}

export interface NetworkStatusResponse {
  generated_at: string
  lines: LineStatus[]
  feed: FeedHealth
}

export interface StartTripIn {
  commute_id: string
  signature: string
  summary: string
  forecast_p10: number
  forecast_p50: number
  forecast_p90: number
  followed_alert_id?: string
}

export interface ScenarioList {
  scenarios: string[]
  current: string | null
}

function normaliseScenarios(raw: unknown): ScenarioList {
  const toId = (s: unknown) =>
    typeof s === 'string' ? s : typeof s === 'object' && s ? String((s as { id?: string; name?: string }).id ?? (s as { name?: string }).name ?? '') : ''
  if (Array.isArray(raw)) return { scenarios: raw.map(toId).filter(Boolean), current: null }
  if (raw && typeof raw === 'object') {
    const r = raw as Record<string, unknown>
    const src = Array.isArray(r.available) ? r.available : r.scenarios
    const list = Array.isArray(src) ? src.map(toId).filter(Boolean) : []
    const current = (r.current ?? r.scenario ?? r.active ?? null) as string | null
    return { scenarios: list, current }
  }
  return { scenarios: [], current: null }
}

export const api = {
  createUser: () => request<{ user_id: string; token: string }>('POST', '/v1/users'),
  me: () => request<User>('GET', '/v1/me'),
  patchMe: (patch: Partial<User>) => request<User>('PATCH', '/v1/me', patch),
  pushKey: () => request<{ public_key: string }>('GET', '/v1/push/key'),
  subscribePush: (subscription: PushSubscriptionJSON) => request<User>('POST', '/v1/push/subscribe', { subscription }),
  unsubscribePush: () => request<User>('DELETE', '/v1/push/subscribe'),
  setPushToken: (push_token: string | null) => request<User>('PATCH', '/v1/me', { push_token }),
  testPush: () => request<{ result: 'sent' | 'gone' | 'failed' }>('POST', '/v1/push/test'),
  deleteMe: () => request<unknown>('DELETE', '/v1/me'),
  deleteHistory: () => request<{ trips_deleted: number; alerts_deleted: number }>('DELETE', '/v1/me/history'),
  onboarding: (body: OnboardingIn) => request<unknown>('POST', '/v1/onboarding', body),

  // Addresses, coordinates and live positions go in request bodies, never URLs (URLs end up in server logs).
  searchPlaces: (q: string) => request<PlaceSearchResult[]>('POST', '/v1/places/search', { q }),
  tripLive: (id: string, pos?: { lat: number; lon: number } | null) =>
    request<LiveTrip>('POST', `/v1/trips/${id}/live`, pos ? { lat: pos.lat, lon: pos.lon } : {}),
  cancelTrip: (id: string) => request<unknown>('DELETE', `/v1/trips/${id}`),
  nearbyStops: (lat: number, lon: number) => request<NearbyStop[]>('POST', '/v1/places/nearby-stops', { lat, lon }),
  places: () => request<Place[]>('GET', '/v1/places'),
  patchPlace: (id: string, patch: Partial<Omit<Place, 'id'>>) => request<Place>('PATCH', `/v1/places/${id}`, patch),
  deletePlace: (id: string) => request<unknown>('DELETE', `/v1/places/${id}`),

  commutes: () => request<Commute[]>('GET', '/v1/commutes'),
  patchCommute: (
    id: string,
    patch: Partial<Pick<Commute, 'days' | 'window_start' | 'window_end' | 'preference' | 'alerts_enabled'>>,
  ) => request<Commute>('PATCH', `/v1/commutes/${id}`, patch),
  compare: (id: string, preference?: Preference) =>
    request<CommuteEvaluation>(
      'GET',
      `/v1/commutes/${id}/compare${preference ? `?preference=${encodeURIComponent(preference)}` : ''}`,
    ),
  setUsual: (id: string, signature: string) => request<Commute>('PUT', `/v1/commutes/${id}/usual`, { signature }),

  dashboard: () => request<Dashboard>('GET', '/v1/dashboard'),
  network: () => request<NetworkStatusResponse>('GET', '/v1/network/status'),

  trips: () => request<Trip[]>('GET', '/v1/trips'),
  startTrip: (body: StartTripIn) => request<Trip>('POST', '/v1/trips', body),
  arrive: (id: string) => request<Trip>('POST', `/v1/trips/${id}/arrive`, {}),

  alerts: () => request<Alert[]>('GET', '/v1/alerts'),
  markAlertsRead: () => request<unknown>('POST', '/v1/alerts/read'),
  alertFeedback: (id: string, feedback: NonNullable<Alert['feedback']>) =>
    request<Alert>('POST', `/v1/alerts/${id}/feedback`, { feedback }),

  insights: () => request<Insights>('GET', '/v1/insights'),

  devScenarios: async () => normaliseScenarios(await request<unknown>('GET', '/v1/dev/scenarios')),
  setScenario: (scenario: string) => request<unknown>('POST', '/v1/dev/scenario', { scenario }),
  checkNow: () => request<unknown>('POST', '/v1/dev/check-now'),
  seed: () => request<unknown>('POST', '/v1/dev/seed'),
}
