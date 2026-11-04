'use client'

import 'leaflet/dist/leaflet.css'
import { useEffect } from 'react'
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import type { LatLngBoundsExpression, LatLngExpression } from 'leaflet'
import { modeColors } from '@/lib/paxen-tokens'
import type { LiveTrip } from '@/lib/types'

// OpenStreetMap's standard tiles are fine for a low-volume pilot (with attribution). For a public launch, point
// NEXT_PUBLIC_MAP_TILES at a commercial tile provider (e.g. MapTiler, Stadia) per OSM's tile usage policy.
const TILES = process.env.NEXT_PUBLIC_MAP_TILES ?? 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

type Pt = [number, number]

function FitTo({ bounds, follow }: { bounds: LatLngBoundsExpression | null; follow: Pt | null }) {
  const map = useMap()
  useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [28, 28] })
  }, [map, bounds])
  useEffect(() => {
    if (follow) map.panTo(follow, { animate: true })
  }, [map, follow])
  return null
}

export default function TripMap({ trip, position, follow }: { trip: LiveTrip; position: Pt | null; follow: boolean }) {
  const legs = trip.legs.filter((l) => l.path && l.path.length > 1)
  const all: Pt[] = legs.flatMap((l) => l.path as Pt[])
  if (trip.dest) all.push([trip.dest.lat, trip.dest.lon])
  if (all.length < 2) return null
  const lats = all.map((p) => p[0])
  const lons = all.map((p) => p[1])
  const bounds: LatLngBoundsExpression = [
    [Math.min(...lats), Math.min(...lons)],
    [Math.max(...lats), Math.max(...lons)],
  ]
  const current = trip.current_leg ?? 0

  return (
    <MapContainer
      bounds={bounds}
      boundsOptions={{ padding: [28, 28] }}
      zoomControl={false}
      attributionControl
      scrollWheelZoom={false}
      className="h-full w-full"
      style={{ background: 'var(--px-surface-sunken, #eee)' }}
    >
      <TileLayer url={TILES} attribution={ATTRIBUTION} maxZoom={19} />
      <FitTo bounds={trip.status === 'active' ? null : bounds} follow={follow ? position : null} />
      {trip.legs.map((l, i) => {
        if (!l.path || l.path.length < 2) return null
        const walking = l.mode === 'walking'
        const colour = walking ? '#6b7280' : (modeColors[l.mode]?.bg ?? '#0f5f63')
        const done = trip.status === 'active' && i < current
        return (
          <Polyline
            key={i}
            positions={l.path as LatLngExpression[]}
            pathOptions={{
              color: colour,
              weight: walking ? 4 : 6,
              opacity: done ? 0.35 : 0.95,
              dashArray: walking ? '2 8' : undefined,
              lineCap: 'round',
            }}
          />
        )
      })}
      {trip.legs.map((l, i) =>
        l.mode !== 'walking' && l.path?.length ? (
          <CircleMarker
            key={`stop-${i}`}
            center={l.path[0] as LatLngExpression}
            radius={6}
            pathOptions={{ color: '#ffffff', weight: 2, fillColor: modeColors[l.mode]?.bg ?? '#0f5f63', fillOpacity: 1 }}
          >
            <Tooltip direction="top" offset={[0, -6]}>
              Board {l.line_name ?? ''} at {l.from}
            </Tooltip>
          </CircleMarker>
        ) : null,
      )}
      {trip.dest && (
        <CircleMarker
          center={[trip.dest.lat, trip.dest.lon]}
          radius={8}
          pathOptions={{ color: '#ffffff', weight: 3, fillColor: '#111827', fillOpacity: 1 }}
        >
          <Tooltip direction="top" offset={[0, -8]} permanent>
            {trip.dest.name}
          </Tooltip>
        </CircleMarker>
      )}
      {position && (
        <>
          <CircleMarker center={position} radius={16} pathOptions={{ stroke: false, fillColor: '#2563eb', fillOpacity: 0.18 }} />
          <CircleMarker center={position} radius={7} pathOptions={{ color: '#ffffff', weight: 3, fillColor: '#2563eb', fillOpacity: 1 }}>
            <Tooltip direction="top" offset={[0, -8]}>
              You
            </Tooltip>
          </CircleMarker>
        </>
      )}
    </MapContainer>
  )
}
