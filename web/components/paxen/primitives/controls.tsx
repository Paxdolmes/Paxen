'use client'

import { useId, type ReactNode } from 'react'
import { Minus, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Text, textStyle } from './text'

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-8 w-13 shrink-0 rounded-full transition-colors before:absolute before:-inset-x-1 before:-inset-y-2 before:content-[''] disabled:opacity-50",
        checked ? 'bg-px-brand' : 'bg-px-border-strong',
      )}
    >
      <span
        className={cn(
          'absolute left-1 top-1 size-6 rounded-full bg-px-surface shadow-px-card transition-transform',
          checked && 'translate-x-5',
        )}
        aria-hidden
      />
    </button>
  )
}

/** A settings row: label + description on the left, control on the right. */
export function SettingRow({
  title,
  description,
  control,
  htmlFor,
}: {
  title: string
  description?: ReactNode
  control: ReactNode
  htmlFor?: string
}) {
  const Label = htmlFor ? 'label' : 'div'
  return (
    <div className="flex min-h-14 items-center justify-between gap-4 px-5 py-3">
      <Label htmlFor={htmlFor} className="flex min-w-0 flex-col gap-0.5">
        <Text variant="callout" as="span">
          {title}
        </Text>
        {description && (
          <Text variant="footnote" as="span" tone="secondary" className="text-pretty">
            {description}
          </Text>
        )}
      </Label>
      {control}
    </div>
  )
}

export function Stepper({
  value,
  onChange,
  min,
  max,
  unit,
  label,
}: {
  value: number
  onChange: (v: number) => void
  min: number
  max: number
  unit: string
  label: string
}) {
  const btn =
    'flex size-11 items-center justify-center rounded-full bg-px-surface-sunken text-px-text transition-colors hover:bg-px-border disabled:opacity-40'
  return (
    <div className="flex shrink-0 items-center gap-2" role="group" aria-label={label}>
      <button type="button" className={btn} onClick={() => onChange(value - 1)} disabled={value <= min} aria-label={`Decrease ${label}`}>
        <Minus className="size-4" aria-hidden />
      </button>
      <span className="min-w-14 text-center tabular" style={{ ...textStyle('bodyStrong') }} aria-live="polite">
        {value} {unit}
      </span>
      <button type="button" className={btn} onClick={() => onChange(value + 1)} disabled={value >= max} aria-label={`Increase ${label}`}>
        <Plus className="size-4" aria-hidden />
      </button>
    </div>
  )
}

export function TimeField({
  label,
  value,
  onChange,
  className,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  className?: string
}) {
  const id = useId()
  return (
    <div className={cn('flex flex-1 flex-col gap-1', className)}>
      <Text variant="caption" as="label" htmlFor={id} tone="secondary">
        {label}
      </Text>
      <input
        id={id}
        type="time"
        step={300}
        value={value}
        onChange={(e) => e.target.value && onChange(e.target.value)}
        className="h-12 w-full rounded-px-sm border border-px-border-strong bg-px-surface px-3 text-px-text tabular"
        style={textStyle('bodyStrong')}
      />
    </div>
  )
}

export function SelectField<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  const id = useId()
  return (
    <div className="flex flex-col gap-1">
      <Text variant="caption" as="label" htmlFor={id} tone="secondary">
        {label}
      </Text>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value as T)}
        className="h-12 w-full appearance-none rounded-px-sm border border-px-border-strong bg-px-surface px-3 text-px-text"
        style={textStyle('callout')}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}
