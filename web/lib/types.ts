// Paxen API contract (backend/paxen/serialize.py). All times are ISO-8601 strings with offsets.

export type Preference = 'balanced' | 'fastest' | 'reliable' | 'least_walking' | 'fewest_changes'
export type LineCategory = 'good' | 'minor' | 'severe' | 'part_suspended' | 'suspended'
export type CommuteStatus = 'normal' | 'watch' | 'slower' | 'disrupted' | 'unknown'
export type Confidence = 'high' | 'medium' | 'low'
export type Mode = 'walking' | 'tube' | 'overground' | 'elizabeth-line' | 'national-rail' | 'dlr' | 'bus' | string

export interface Place {
  id: string
  label: 'home' | 'work' | 'other'
  name: string
  lat: number
  lon: number
  source: 'manual' | 'pin' | 'saved' | 'inferred'
  confirmed: boolean
  stops: ChosenStop[] // stations/stops the user chose for this place; [] = let Paxen choose
}

/** A station or stop near a place (POST /v1/places/nearby-stops), nearest first. */
export interface NearbyStop {
  stop_id: string
  name: string
  kind: 'station' | 'bus'
  lat: number
  lon: number
  distance_m: number
  walk_min: number
  modes: string[]
  lines: string[]
  hub: string | null
  indicator: string | null // bus stop letter, e.g. "Stop K"
  towards: string | null
}

export type ChosenStop = Pick<NearbyStop, 'stop_id' | 'name' | 'kind' | 'lat' | 'lon' | 'walk_min' | 'hub' | 'modes' | 'lines' | 'indicator'>

export interface PlaceSearchResult {
  name: string
  lat: number
  lon: number
  kind: 'station' | 'address' | 'place'
  stop_id: string | null
  detail: string | null
}

export interface Commute {
  id: string
  name: string // "To work" | "Home"
  origin: Place
  dest: Place
  days: number[] // 0 = Mon … 6 = Sun
  window_start: string // "08:00"
  window_end: string
  preference: Preference
  alerts_enabled: boolean
  usual_summary: string | null // "Victoria"
  usual_signature: string | null
}

export interface Leg {
  mode: Mode
  line_id: string | null
  line_name: string | null
  from: string
  to: string
  direction: string | null
  wait_min: number // forecast wait at the boarding stop
  ride_min: number // walking legs: walk time
  live: boolean // wait is based on live arrivals (+ correction model)
  status: LineCategory
  next_departures_min: number[] // relative to when you reach the stop
  path?: [number, number][] | null // route shape (lat, lon); included by /compare and live trips
}

export interface Disruption {
  line_id: string
  line_name: string
  category: LineCategory
  description: string
  reason: string | null
}

export interface RouteOption {
  id: string // route signature; pass back to set usual route / log a trip
  summary: string // "Weaver line → Central"
  is_usual: boolean
  is_recommended: boolean
  feasible: boolean // false = a line on this route is suspended
  depart_at: string
  arrive_at: string // median forecast
  arrive_range: [string, string] // 10th–90th percentile arrival
  duration: { p10: number; p50: number; p90: number } // door-to-door minutes
  nominal_min: number // timetable duration with no disruption
  fare: { pence: number; peak_pence: number | null; off_peak_pence: number | null } | null
  vs_usual_min: number | null // + slower / − faster than the usual route today
  walking_min: number
  changes: number
  confidence: Confidence
  on_time_chance: number // 0–1: chance of arriving within 5 min of normal
  reliability: { pct: number; n: number; label: string } | null // from the user's own past trips
  crowding: { level: 'quiet' | 'typical' | 'busy' | 'busier' | 'very_busy' | 'n/a'; label: string; basis: string | null }
  disruptions: Disruption[]
  live_data: boolean
  legs: Leg[]
}

export interface Baseline {
  p50: number | null
  p80: number | null
  n: number
  basis: 'personal' | 'network' | 'none'
  label: string // "Your last 15 trips" | "Typical journey time (learning your routine)"
}

export interface CommuteEvaluation {
  commute: Commute
  active: boolean // inside (or 45 min before) its time window today
  depart_at: string
  status: CommuteStatus
  headline: string // "Your usual commute is 18 minutes slower today"
  detail: string // reason + recommendation sentence
  delta_min: number | null // usual route today vs personal baseline
  gain_min: number | null // minutes saved by the recommended route vs usual
  preference: Preference
  chosen_stops_honoured: boolean // false: nothing runs via the user's chosen stations right now; all routes shown
  conditions?: Conditions | null
  baseline: Baseline
  usual: RouteOption | null
  recommended: RouteOption | null
  options: RouteOption[] // ranked by preference (dashboard: top 3 + usual)
}

export interface FeedHealth {
  last_success_at: string | null
  last_error_at: string | null
  age_s: number | null
  fresh: boolean
  predictions_recorded: number
  observed_arrivals: number
}

export interface LineStatus {
  line_id: string
  line_name: string
  mode: Mode
  category: LineCategory
  description: string // "Severe delays"
  reason: string | null
  on_my_routes: boolean
}

export interface User {
  id: string
  name: string | null
  quiet_start: string
  quiet_end: string
  monitoring_paused: boolean
  alert_threshold_min: number // alert when usual is this much slower than normal
  min_gain_min: number // only suggest alternatives at least this much better
  push_enabled: boolean
}

export interface Dashboard {
  generated_at: string
  user: User
  provider: 'sim' | 'tfl'
  simulated: boolean
  feed: FeedHealth
  active_commute_id: string | null
  commutes: CommuteEvaluation[]
  network: LineStatus[] // lines on my routes first, worst first
  unread_alerts: number
  upcoming?: UpcomingDisruption[] // planned closures in the next 7 days on my lines
}

export interface Weather {
  time: string // "08:00"
  rain_prob: number | null
  rain_mm: number | null
  temp_c: number | null
  wet: boolean
  summary: string // "Dry" | "Chance of rain" | "Rain likely" | "Heavy rain"
}

export interface AirQuality {
  band: string // "Low" | "Moderate" | "High" | "Very High"
  level: number | null
  summary: string
  tomorrow_band: string | null
  usual_band: string | null
  history_days: number
  worse_than_usual: boolean
  label: string // "High today (usually Low)"
}

export interface Conditions {
  weather?: Weather | null
  air_quality?: AirQuality | null
  walking_note?: string | null // why long walks are ranked lower today
}

export interface UpcomingDisruption {
  line_id: string
  line_name: string
  mode: Mode
  category: LineCategory
  description: string
  reason: string | null
  from: string
  to: string | null
  starts_local: string // "Mon 09 Nov, 22:45"
  commutes: string[] // which of my commutes use this line
}

export interface LiveTrip {
  trip_id: string
  status: 'active' | 'arrived' | 'auto_closed' | 'too_fast'
  summary: string | null
  started_at: string
  elapsed_min: number
  legs: { mode: Mode; line_id: string | null; line_name: string | null; from: string; to: string;
          direction: string | null; wait_min: number; ride_min: number; path: [number, number][] | null }[]
  origin: { name: string; lat: number; lon: number } | null
  dest: { name: string; lat: number; lon: number } | null
  forecast_at_start: { p10: number; p50: number; p90: number } | null
  // active only
  located_by?: 'position' | 'clock'
  current_leg?: number
  phase?: 'walking' | 'waiting' | 'on_board'
  progress?: number
  remaining_min?: { p10: number; p50: number; p90: number }
  eta?: string
  eta_range?: [string, string]
  confidence?: Confidence
  next_departure?: { line_name: string | null; line_id: string; stop: string; direction: string | null;
                     wait_min: number; departures_min: number[]; live: boolean; leg_index: number } | null
  disruptions?: Disruption[]
  // ended
  duration_min?: number | null
  vs_forecast_min?: number | null
}

export interface Alert {
  id: string
  commute_id: string | null
  created_at: string
  kind: 'better_route' | 'leave_earlier' | 'usual_unavailable'
  title: string
  body: string
  confidence: Confidence
  delta_min: number | null
  gain_min: number | null
  recommended_summary: string | null
  recommended_signature: string | null
  read: boolean
  feedback: 'useful' | 'not_useful' | 'inaccurate' | null
  delivered: 'inbox' | 'push' | 'push_failed'
}

export interface Trip {
  id: string
  commute_id: string | null
  summary: string | null
  signature: string | null
  route_key: string
  started_at: string
  arrived_at: string | null
  duration_min: number | null
  forecast: { p10: number | null; p50: number | null; p90: number | null }
  followed_alert_id: string | null
  source: string
}

export interface ErrorMetrics { n: number; mae_s?: number; bias_s?: number; within_2m?: number; within_5m?: number }

export interface Insights {
  personal: {
    window_days: number
    trips: number
    commute_days: number
    alerts: number
    alerts_rated_useful: number
    alerts_rated: number
    alerts_followed: number
    minutes_saved: number
    journey_forecast_mae_min: number | null
    interval_hit_rate: number | null
    routes_used: number
  }
  model: {
    status: 'no_model' | 'shadow' | 'active'
    message?: string
    version?: number
    trained_at?: string
    provider?: ErrorMetrics // raw TfL-style countdown accuracy
    corrected?: ErrorMetrics // after Paxen's correction model
    interval_coverage?: number
    by_lead?: Record<string, { provider: ErrorMetrics; corrected: ErrorMetrics }>
    by_line?: Record<string, { provider: ErrorMetrics; corrected: ErrorMetrics }>
    note?: string
  }
  feed: FeedHealth
  alerts_total: number
}

/* Endpoints (Authorization: Bearer <token>, except POST /v1/users and GET /v1/health)
POST   /v1/users                         -> { user_id, token }        anonymous device account
GET    /v1/health                        -> { ok, provider, simulated, scenario, feed }
GET    /v1/me | PATCH /v1/me (Partial<User> + push_token) | DELETE /v1/me
DELETE /v1/me/history                    -> { trips_deleted, alerts_deleted }
POST   /v1/onboarding  { name?, home: PlaceIn, work: PlaceIn, days, morning: {start,end}, evening: {start,end}, preference }
                                         PlaceIn = { label, name, lat, lon, source }
GET    /v1/places/search?q=              -> PlaceSearchResult[]
GET    /v1/places | PATCH /v1/places/:id | DELETE /v1/places/:id
GET    /v1/commutes | PATCH /v1/commutes/:id { days?, window_start?, window_end?, preference?, alerts_enabled? }
GET    /v1/commutes/:id/compare?preference=&depart_at=   -> CommuteEvaluation (all options)
PUT    /v1/commutes/:id/usual { signature }              -> Commute
GET    /v1/dashboard                     -> Dashboard
GET    /v1/network/status                -> { generated_at, lines: LineStatus[], feed }
GET    /v1/trips | POST /v1/trips { commute_id, signature, summary, forecast_p10, forecast_p50, forecast_p90, followed_alert_id? }
POST   /v1/trips/:id/arrive {}           -> Trip (duration computed)
GET    /v1/alerts | POST /v1/alerts/read | POST /v1/alerts/:id/feedback { feedback, note? }
GET    /v1/insights                      -> Insights
Simulator only: GET /v1/dev/scenarios, POST /v1/dev/scenario { scenario }, POST /v1/dev/check-now, POST /v1/dev/seed
  scenarios: auto | normal | victoria-severe | victoria-suspended | central-minor | weaver-suspended | mixed
*/
