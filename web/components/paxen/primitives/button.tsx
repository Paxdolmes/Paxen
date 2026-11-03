import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { layout } from '@/lib/paxen-tokens'
import { textStyle } from './text'

type Variant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger'
type Size = 'lg' | 'md' | 'sm'

const variantClass: Record<Variant, string> = {
  primary: 'bg-px-brand text-px-on-brand hover:bg-px-brand-pressed active:bg-px-brand-pressed',
  secondary: 'bg-px-surface-sunken text-px-text hover:bg-px-border',
  outline: 'border border-px-border-strong bg-px-surface text-px-text hover:bg-px-surface-sunken',
  ghost: 'bg-transparent text-px-brand hover:bg-px-brand-soft',
  danger: 'bg-px-attention-soft text-px-on-attention-soft hover:brightness-95',
}

const sizeClass: Record<Size, string> = {
  lg: 'rounded-px-md px-6 gap-2',
  md: 'rounded-px-sm px-4 gap-2',
  sm: 'rounded-px-sm px-3 gap-1.5',
}

export interface PxButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  block?: boolean
  loading?: boolean
  icon?: ReactNode
}

export function Button({
  variant = 'primary',
  size = 'lg',
  block,
  loading,
  icon,
  className,
  children,
  disabled,
  style,
  type = 'button',
  ...props
}: PxButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex shrink-0 select-none items-center justify-center transition-[background-color,transform,filter] duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50',
        variantClass[variant],
        sizeClass[size],
        block && 'w-full',
        className,
      )}
      style={{
        height: layout.buttonHeight[size],
        ...textStyle(size === 'sm' ? 'subhead' : 'bodyStrong'),
        fontWeight: 600,
        ...style,
      }}
      {...props}
    >
      {loading ? <Loader2 className="size-5 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  )
}
