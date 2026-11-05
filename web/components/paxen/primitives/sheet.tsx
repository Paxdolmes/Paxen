'use client'

import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { Button } from './button'
import { Text } from './text'

interface SheetProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
}

/** Native <dialog> bottom sheet: focus trap, Esc and backdrop close for free. */
export function Sheet({ open, onClose, title, children, footer }: SheetProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      className="fixed inset-x-0 bottom-0 top-auto m-0 mx-auto w-full max-w-[430px] max-h-[85dvh] rounded-t-px-xl bg-px-surface-raised p-0 text-px-text shadow-px-raised backdrop:bg-px-overlay open:px-rise"
    >
      <div className="flex flex-col gap-4 px-5 pb-safe pt-3">
        <div className="mx-auto h-1 w-10 rounded-full bg-px-border-strong" aria-hidden />
        <div className="flex items-start justify-between gap-3">
          <Text id={titleId} variant="title2" as="h2" className="text-balance">
            {title}
          </Text>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-2 -mt-1 flex size-11 shrink-0 items-center justify-center rounded-full text-px-text-secondary hover:bg-px-surface-sunken"
          >
            <X className="size-5" aria-hidden />
          </button>
        </div>
        <div className="flex flex-col gap-3">{children}</div>
        <div className="flex flex-col gap-2 pb-5">{footer}</div>
      </div>
    </dialog>
  )
}

export function ConfirmSheet({
  open,
  onClose,
  title,
  body,
  confirmLabel,
  onConfirm,
  loading,
}: {
  open: boolean
  onClose: () => void
  title: string
  body: ReactNode
  confirmLabel: string
  onConfirm: () => void
  loading?: boolean
}) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="danger" block onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
          <Button variant="secondary" block onClick={onClose} disabled={loading}>
            Cancel
          </Button>
        </>
      }
    >
      <Text variant="body" tone="secondary" className="text-pretty">
        {body}
      </Text>
    </Sheet>
  )
}
