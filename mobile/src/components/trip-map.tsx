import { useEffect, useMemo, useRef } from 'react'
import MapView, { Circle, Marker, Polyline } from 'react-native-maps'
import { modeColors } from '@/shared/paxen-tokens'
import type { LiveTrip } from '@/shared/types'
import { alpha } from '@/lib/theme'

type Pt = [number, number]

/** The trip on Apple Maps: each leg in its mode's colour (walks dotted), stops, destination and you. */
export default function TripMap({ trip, position, follow }: { trip: LiveTrip; position: Pt | null; follow: boolean }) {
  const ref = useRef<MapView>(null)
  const all = useMemo(() => {
    const pts: Pt[] = trip.legs.flatMap((l) => (l.path ?? []) as Pt[])
    if (trip.dest) pts.push([trip.dest.lat, trip.dest.lon])
    return pts
  }, [trip])

  useEffect(() => {
    if (all.length < 2) return
    const t = setTimeout(
      () => ref.current?.fitToCoordinates(all.map(([latitude, longitude]) => ({ latitude, longitude })), { edgePadding: { top: 40, right: 40, bottom: 40, left: 40 }, animated: false }),
      50,
    )
    return () => clearTimeout(t)
  }, [all])

  useEffect(() => {
    if (follow && position) ref.current?.animateCamera({ center: { latitude: position[0], longitude: position[1] } }, { duration: 500 })
  }, [follow, position])

  if (all.length < 2) return null
  const current = trip.current_leg ?? 0

  return (
    <MapView ref={ref} style={{ flex: 1 }} showsCompass={false} showsPointsOfInterests={false} pitchEnabled={false} toolbarEnabled={false}>
      {trip.legs.map((l, i) => {
        if (!l.path || l.path.length < 2) return null
        const walking = l.mode === 'walking'
        const done = trip.status === 'active' && i < current
        return (
          <Polyline
            key={`leg-${i}`}
            coordinates={(l.path as Pt[]).map(([latitude, longitude]) => ({ latitude, longitude }))}
            strokeColor={alpha(walking ? '#6b7280' : (modeColors[l.mode]?.bg ?? '#0f5f63'), done ? 0.35 : 0.95)}
            strokeWidth={walking ? 4 : 6}
            lineDashPattern={walking ? [2, 8] : undefined}
            lineCap="round"
          />
        )
      })}
      {trip.legs.map((l, i) =>
        l.mode !== 'walking' && l.path?.length ? (
          <Marker key={`stop-${i}`} coordinate={{ latitude: l.path[0][0], longitude: l.path[0][1] }} title={`Board ${l.line_name ?? ''} at ${l.from}`} pinColor={modeColors[l.mode]?.bg ?? '#0f5f63'} />
        ) : null,
      )}
      {trip.dest && <Marker coordinate={{ latitude: trip.dest.lat, longitude: trip.dest.lon }} title={trip.dest.name} pinColor="#111827" />}
      {position && (
        <>
          <Circle center={{ latitude: position[0], longitude: position[1] }} radius={40} strokeWidth={0} fillColor="rgba(37, 99, 235, 0.18)" />
          <Circle center={{ latitude: position[0], longitude: position[1] }} radius={10} strokeWidth={3} strokeColor="#ffffff" fillColor="#2563eb" />
        </>
      )}
    </MapView>
  )
}
