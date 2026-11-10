import { useState, type ReactNode } from 'react'
import { Platform, Pressable, Switch as RNSwitch, TextInput, View } from 'react-native'
import DateTimePicker from '@react-native-community/datetimepicker'
import { Check, ChevronDown, Minus, Plus } from 'lucide-react-native'
import { radii } from '@/shared/paxen-tokens'
import { usePalette } from '@/lib/theme'
import { Sheet } from './sheet'
import { Text, textStyle } from './text'
import { Button } from './ui'

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  const p = usePalette()
  return (
    <RNSwitch
      accessibilityLabel={label}
      value={checked}
      onValueChange={onChange}
      disabled={disabled}
      trackColor={{ true: p.brand, false: p.borderStrong }}
      thumbColor="#FFFFFF"
      ios_backgroundColor={p.borderStrong}
    />
  )
}

/** A settings row: label + description on the left, control on the right. */
export function SettingRow({ title, description, control }: { title: string; description?: string; control: ReactNode }) {
  return (
    <View style={{ minHeight: 56, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingHorizontal: 20, paddingVertical: 12 }}>
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="callout">{title}</Text>
        {description ? (
          <Text variant="footnote" tone="secondary">
            {description}
          </Text>
        ) : null}
      </View>
      {control}
    </View>
  )
}

export function Stepper({ value, onChange, min, max, unit, label }: { value: number; onChange: (v: number) => void; min: number; max: number; unit: string; label: string }) {
  const p = usePalette()
  const btn = (dir: -1 | 1) => {
    const off = dir < 0 ? value <= min : value >= max
    const Icon = dir < 0 ? Minus : Plus
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${dir < 0 ? 'Decrease' : 'Increase'} ${label}`}
        disabled={off}
        onPress={() => onChange(value + dir)}
        style={{ width: 40, height: 40, borderRadius: 20, backgroundColor: p.surfaceSunken, alignItems: 'center', justifyContent: 'center', opacity: off ? 0.4 : 1 }}
      >
        <Icon size={16} color={p.text} />
      </Pressable>
    )
  }
  return (
    <View accessibilityLabel={label} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
      {btn(-1)}
      <Text variant="bodyStrong" tabular style={{ minWidth: 52, textAlign: 'center' }}>
        {value} {unit}
      </Text>
      {btn(1)}
    </View>
  )
}

const toDate = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number)
  const d = new Date()
  d.setHours(h || 0, m || 0, 0, 0)
  return d
}
const toHHMM = (d: Date) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`

/** A time of day ("08:30"). Tapping opens the iPhone's time wheel in 5-minute steps. */
export function TimeField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const p = usePalette()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(value)
  const box = {
    height: 48,
    borderRadius: radii.sm,
    borderWidth: 1,
    borderColor: p.borderStrong,
    backgroundColor: p.surface,
    paddingHorizontal: 12,
    justifyContent: 'center' as const,
  }
  if (Platform.OS === 'web') {
    return (
      <View style={{ flex: 1, gap: 4 }}>
        <Text variant="caption" tone="secondary">
          {label}
        </Text>
        <TextInput
          value={value}
          onChangeText={(t) => /^\d{2}:\d{2}$/.test(t) && onChange(t)}
          style={[box, textStyle('bodyStrong'), { color: p.text }]}
          accessibilityLabel={label}
        />
      </View>
    )
  }
  return (
    <View style={{ flex: 1, gap: 4 }}>
      <Text variant="caption" tone="secondary">
        {label}
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}, ${value}`}
        onPress={() => {
          setDraft(value)
          setOpen(true)
        }}
        style={box}
      >
        <Text variant="bodyStrong" tabular>
          {value}
        </Text>
      </Pressable>
      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title={label}
        footer={
          <Button
            block
            onPress={() => {
              onChange(draft)
              setOpen(false)
            }}
          >
            Done
          </Button>
        }
      >
        <DateTimePicker
          mode="time"
          display="spinner"
          minuteInterval={5}
          value={toDate(draft)}
          is24Hour
          locale="en-GB"
          onChange={(_, d) => d && setDraft(toHHMM(d))}
          style={{ alignSelf: 'center' }}
        />
      </Sheet>
    </View>
  )
}

/** A choice from a short list, opened as a sheet of options. */
export function SelectField<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  const p = usePalette()
  const [open, setOpen] = useState(false)
  const current = options.find((o) => o.value === value)
  return (
    <View style={{ gap: 4 }}>
      <Text variant="caption" tone="secondary">
        {label}
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}, ${current?.label ?? ''}`}
        onPress={() => setOpen(true)}
        style={{
          height: 48,
          borderRadius: radii.sm,
          borderWidth: 1,
          borderColor: p.borderStrong,
          backgroundColor: p.surface,
          paddingHorizontal: 12,
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <Text variant="callout">{current?.label ?? 'Choose'}</Text>
        <ChevronDown size={18} color={p.textSecondary} />
      </Pressable>
      <Sheet open={open} onClose={() => setOpen(false)} title={label}>
        {options.map((o) => {
          const sel = o.value === value
          return (
            <Pressable
              key={o.value}
              accessibilityRole="radio"
              accessibilityState={{ selected: sel }}
              onPress={() => {
                onChange(o.value)
                setOpen(false)
              }}
              style={{
                minHeight: 52,
                borderRadius: radii.md,
                borderWidth: 1,
                borderColor: sel ? p.brand : p.border,
                backgroundColor: sel ? p.brandSoft : p.surface,
                paddingHorizontal: 16,
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <Text variant="callout" color={sel ? p.onBrandSoft : p.text} style={{ fontWeight: '600' }}>
                {o.label}
              </Text>
              {sel && <Check size={20} color={p.brand} />}
            </Pressable>
          )
        })}
      </Sheet>
    </View>
  )
}
