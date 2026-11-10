import { useState } from 'react'
import { Pressable, TextInput, View } from 'react-native'
import { Building2, Bus, Check, Footprints, MapPin, Search, TrainFront } from 'lucide-react-native'
import { radii } from '@/shared/paxen-tokens'
import type { ChosenStop, NearbyStop, PlaceSearchResult } from '@/shared/types'
import { useNearbyStops, usePlaceSearch } from '@/lib/hooks'
import { usePalette } from '@/lib/theme'
import { Text, textStyle } from './text'
import { Skeleton } from './ui'

const kindIcon = { station: TrainFront, address: Building2, place: MapPin } as const

export function PlaceSearch({
  label,
  placeholder,
  selected,
  onSelect,
  autoFocus,
}: {
  label: string
  placeholder: string
  selected: PlaceSearchResult | null
  onSelect: (p: PlaceSearchResult) => void
  autoFocus?: boolean
}) {
  const p = usePalette()
  const [q, setQ] = useState('')
  const { data, error, isLoading } = usePlaceSearch(q)
  const term = q.trim()

  return (
    <View style={{ gap: 12 }}>
      <View style={{ justifyContent: 'center' }}>
        <View style={{ position: 'absolute', left: 16, zIndex: 1 }} pointerEvents="none">
          <Search size={20} color={p.textTertiary} />
        </View>
        <TextInput
          accessibilityLabel={label}
          autoFocus={autoFocus}
          autoCorrect={false}
          autoCapitalize="words"
          returnKeyType="search"
          clearButtonMode="while-editing"
          placeholder={placeholder}
          placeholderTextColor={p.textTertiary}
          value={q}
          onChangeText={setQ}
          style={[
            textStyle('body'),
            { height: 56, borderRadius: radii.md, borderWidth: 1, borderColor: p.borderStrong, backgroundColor: p.surface, paddingLeft: 48, paddingRight: 16, color: p.text },
          ]}
        />
      </View>

      {term.length >= 2 && (
        <View accessibilityLiveRegion="polite">
          {isLoading && !data ? (
            <View style={{ gap: 8 }}>
              <Skeleton style={{ height: 56, borderRadius: radii.md }} />
              <Skeleton style={{ height: 56, borderRadius: radii.md }} />
            </View>
          ) : error ? (
            <Text variant="footnote" tone="attention">
              Search isn&apos;t available right now. Try again in a moment.
            </Text>
          ) : data && data.length === 0 ? (
            <Text variant="footnote" tone="secondary">
              No matches for “{term}”. Try a full postcode (e.g. E17 9PH), a street address or a station name.
            </Text>
          ) : (
            <View style={{ gap: 6 }}>
              {data?.map((r) => {
                const Icon = kindIcon[r.kind] ?? MapPin
                const isSel = selected?.name === r.name && selected.lat === r.lat && selected.lon === r.lon
                return (
                  <Pressable
                    key={`${r.name}-${r.lat}-${r.lon}`}
                    accessibilityRole="button"
                    accessibilityState={{ selected: isSel }}
                    onPress={() => {
                      onSelect(r)
                      setQ('') // collapse the list; the chosen place shows below
                    }}
                    style={({ pressed }) => ({
                      minHeight: 56,
                      flexDirection: 'row',
                      alignItems: 'center',
                      gap: 12,
                      borderRadius: radii.md,
                      borderWidth: 1,
                      borderColor: isSel ? p.accent : p.border,
                      backgroundColor: isSel ? p.accentSoft : pressed ? p.surfaceSunken : p.surface,
                      paddingHorizontal: 16,
                      paddingVertical: 10,
                    })}
                  >
                    <Icon size={20} color={p.textSecondary} />
                    <View style={{ flex: 1 }}>
                      <Text variant="callout" style={{ fontWeight: '600' }} numberOfLines={1}>
                        {r.name}
                      </Text>
                      <Text variant="footnote" tone="secondary" numberOfLines={1}>
                        {r.kind === 'station' ? 'Station' : r.kind === 'address' ? 'Address' : 'Place'}
                        {r.detail ? ` · ${r.detail}` : ''}
                      </Text>
                    </View>
                    {isSel && <Check size={20} color={p.accent} />}
                  </Pressable>
                )
              })}
            </View>
          )}
        </View>
      )}

      {selected && term.length < 2 && (
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: radii.md, borderWidth: 1, borderColor: p.accent, backgroundColor: p.accentSoft, paddingHorizontal: 16, paddingVertical: 12 }}>
          <Check size={20} color={p.onAccentSoft} />
          <Text variant="callout" color={p.onAccentSoft} style={{ fontWeight: '600', flex: 1 }}>
            {selected.name}
          </Text>
        </View>
      )}
    </View>
  )
}

const MAX_STOPS = 6

function toChosen(s: NearbyStop): ChosenStop {
  const { stop_id, name, kind, lat, lon, walk_min, hub, modes, lines, indicator } = s
  return { stop_id, name, kind, lat, lon, walk_min, hub, modes, lines, indicator }
}

function StopRow({ stop, selected, onToggle, disabled }: { stop: NearbyStop; selected: boolean; onToggle: () => void; disabled: boolean }) {
  const p = usePalette()
  const Icon = stop.kind === 'bus' ? Bus : TrainFront
  // Bus stops share names; the stop letter and direction are what tell them apart, so they lead the second line.
  const sub =
    stop.kind === 'bus'
      ? [stop.indicator, stop.towards ? `to ${stop.towards}` : null, stop.lines.slice(0, 5).join(', ')].filter(Boolean).join(' · ')
      : stop.lines.slice(0, 5).join(' · ')
  const off = disabled && !selected
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked: selected, disabled: off }}
      onPress={onToggle}
      disabled={off}
      style={{
        minHeight: 56,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        borderRadius: radii.md,
        borderWidth: 1,
        borderColor: selected ? p.accent : p.border,
        backgroundColor: selected ? p.accentSoft : p.surface,
        paddingHorizontal: 16,
        paddingVertical: 10,
        opacity: off ? 0.5 : 1,
      }}
    >
      <View
        style={{
          width: 24,
          height: 24,
          borderRadius: 6,
          borderWidth: 1,
          borderColor: selected ? p.accent : p.borderStrong,
          backgroundColor: selected ? p.accent : p.surface,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {selected && <Check size={16} color={p.onAccent} />}
      </View>
      <Icon size={20} color={p.textSecondary} />
      <View style={{ flex: 1 }}>
        <Text variant="callout" style={{ fontWeight: '600' }} numberOfLines={1}>
          {stop.name}
        </Text>
        {sub ? (
          <Text variant="footnote" tone="secondary" numberOfLines={2}>
            {sub}
          </Text>
        ) : null}
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
        <Footprints size={16} color={p.textSecondary} />
        <Text variant="footnote" tone="secondary">
          {Math.max(1, Math.round(stop.walk_min))} min
        </Text>
      </View>
    </Pressable>
  )
}

/** Lets the user choose which nearby stations/stops they actually use. Nothing is pre-selected. */
export function StopPicker({ lat, lon, value, onChange, placeLabel }: { lat: number | null; lon: number | null; value: ChosenStop[]; onChange: (v: ChosenStop[]) => void; placeLabel: string }) {
  const { data, error, isLoading } = useNearbyStops(lat, lon)
  const chosen = new Set(value.map((s) => s.stop_id))
  const full = value.length >= MAX_STOPS
  const toggle = (s: NearbyStop) => onChange(chosen.has(s.stop_id) ? value.filter((v) => v.stop_id !== s.stop_id) : [...value, toChosen(s)])

  if (lat == null || lon == null) return null
  const stations = (data ?? []).filter((s) => s.kind === 'station')
  const buses = (data ?? []).filter((s) => s.kind === 'bus').slice(0, 6)

  return (
    <View style={{ gap: 16 }} accessibilityLiveRegion="polite">
      <View style={{ gap: 4 }}>
        <Text variant="headline">Which stations do you use?</Text>
        <Text variant="footnote" tone="secondary">
          Pick one or more near {placeLabel}. Paxen plans your routes from these. Skip it to let Paxen choose.
        </Text>
      </View>
      {isLoading && !data ? (
        <View style={{ gap: 8 }}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} style={{ height: 56, borderRadius: radii.md }} />
          ))}
        </View>
      ) : error ? (
        <Text variant="footnote" tone="attention">
          Couldn&apos;t load nearby stations. You can carry on and choose them later in You.
        </Text>
      ) : !data?.length ? (
        <Text variant="footnote" tone="secondary">
          No stations or stops found nearby. Paxen will choose for you.
        </Text>
      ) : (
        <>
          {stations.length > 0 && (
            <View style={{ gap: 8 }}>
              <Text variant="subhead" tone="secondary">
                Stations
              </Text>
              {stations.map((s) => (
                <StopRow key={s.stop_id} stop={s} selected={chosen.has(s.stop_id)} onToggle={() => toggle(s)} disabled={full} />
              ))}
            </View>
          )}
          {buses.length > 0 && (
            <View style={{ gap: 8 }}>
              <Text variant="subhead" tone="secondary">
                Bus stops
              </Text>
              {buses.map((s) => (
                <StopRow key={s.stop_id} stop={s} selected={chosen.has(s.stop_id)} onToggle={() => toggle(s)} disabled={full} />
              ))}
            </View>
          )}
          <Text variant="footnote" tone="secondary">
            {value.length === 0 ? 'None chosen: Paxen will pick the best stations each day.' : `${value.length} chosen${full ? ' (maximum)' : ''}.`}
          </Text>
        </>
      )}
    </View>
  )
}
